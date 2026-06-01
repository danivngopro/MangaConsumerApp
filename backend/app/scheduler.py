from __future__ import annotations

import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import repository
from .asura import AsuraClient
from .scanner import scan_full_catalog, scan_limited_catalog_batch


class ScanScheduler:
    def __init__(self, conn: sqlite3.Connection, client: AsuraClient, library_root: Path) -> None:
        self.conn = conn
        self.client = client
        self.library_root = library_root
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._scan_lock = threading.Lock()
        self._cancel_scan = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="scan-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def run_full_scan_async(self, limit: int | None = None) -> None:
        if limit is not None:
            threading.Thread(target=lambda: self.start_limited_scan(limit), name="limited-scan", daemon=True).start()
            return
        threading.Thread(target=lambda: self.run_full_scan(None), name="manual-full-scan", daemon=True).start()

    def cancel_current_scan(self) -> dict:
        self._cancel_scan.set()
        repository.stop_limited_scan_state(self.conn)
        repository.log(self.conn, "info", "Scan stop requested")
        return {"stopRequested": True, "scanRunning": self.scan_running}

    @property
    def scan_running(self) -> bool:
        return self._scan_lock.locked()

    def run_full_scan(self, limit: int | None = None) -> dict | None:
        if not self._scan_lock.acquire(blocking=False):
            repository.log(self.conn, "info", "Full scan request ignored because a scan is already running")
            return None
        self._cancel_scan.clear()
        try:
            result = scan_full_catalog(
                self.conn,
                self.client,
                self.library_root,
                limit,
                should_stop=self._cancel_scan.is_set,
            )
            if limit is None and not result.get("stopped"):
                repository.set_setting(self.conn, "last_full_scan_at", datetime.now(timezone.utc).isoformat())
            return result
        except Exception as exc:
            repository.log(self.conn, "error", f"Full scan failed: {exc}")
            raise
        finally:
            self._scan_lock.release()

    def start_limited_scan(self, active_threshold: int) -> dict | None:
        active_threshold = max(1, int(active_threshold))
        self._cancel_scan.clear()
        if not repository.start_limited_scan_state(self.conn, active_threshold):
            repository.log(self.conn, "info", "Limited scan start ignored because a batch is already being selected")
            return None
        repository.log(self.conn, "info", f"Limited scan top-up started with active chapter threshold {active_threshold}")
        return self._top_up_limited_scan()

    def run_next_limited_scan_batch(self, claimed: tuple[int, int] | None = None) -> dict | None:
        if claimed is None:
            claimed = repository.claim_limited_scan_batch(self.conn)
            if claimed is None:
                repository.log(self.conn, "info", "Limited scan batch request ignored because another scheduler already claimed it")
                return None
        if not self._scan_lock.acquire(blocking=False):
            repository.log(self.conn, "info", "Limited scan batch request ignored because a scan is already running")
            repository.set_setting(self.conn, "limited_scan_batch_running", "0")
            return None
        try:
            active_threshold, offset = claimed
            result = scan_limited_catalog_batch(
                self.conn,
                self.client,
                self.library_root,
                1,
                offset,
                should_stop=self._cancel_scan.is_set,
            )
            repository.finish_limited_scan_batch(self.conn, result)
            if result.get("stopped"):
                repository.log(self.conn, "info", "Limited scan stopped by user request")
            elif not result["batchMangaIds"] or result["exhausted"]:
                repository.log(self.conn, "info", "Limited scan stopped because the Asura catalog has no more books with downloads in range")
            else:
                active_count = repository.active_download_job_count(self.conn)
                repository.log(
                    self.conn,
                    "info",
                    f"Limited scan top-up added 1 book; active chapters {active_count}/{active_threshold}",
                )
            return result
        except Exception as exc:
            repository.set_setting(self.conn, "limited_scan_batch_running", "0")
            repository.log(self.conn, "error", f"Limited scan batch failed: {exc}")
            raise
        finally:
            self._scan_lock.release()

    def _run(self) -> None:
        while not self._stop.is_set():
            interval_days = int(repository.get_setting(self.conn, "auto_scan_every_days", "0") or "0")
            if interval_days > 0 and self._is_due(interval_days):
                try:
                    self.run_full_scan()
                except Exception:
                    pass
            try:
                self._continue_limited_scan_if_ready()
            except Exception:
                pass
            time.sleep(15)

    def _is_due(self, interval_days: int) -> bool:
        last_value = repository.get_setting(self.conn, "last_full_scan_at", "")
        if not last_value:
            return True
        try:
            last = datetime.fromisoformat(last_value)
        except ValueError:
            return True
        return datetime.now(timezone.utc) - last >= timedelta(days=interval_days)

    def _continue_limited_scan_if_ready(self) -> None:
        if repository.get_setting(self.conn, "limited_scan_active", "0") != "1":
            return
        threshold = int(repository.get_setting(self.conn, "limited_scan_active_threshold", "300") or "300")
        active_count = repository.active_download_job_count(self.conn)
        if active_count >= threshold:
            return
        repository.log(
            self.conn,
            "info",
            f"Active chapters below threshold ({active_count}/{threshold}); finding next book",
        )
        self._top_up_limited_scan()

    def _top_up_limited_scan(self) -> dict | None:
        last_result = None
        while not self._cancel_scan.is_set():
            threshold = int(repository.get_setting(self.conn, "limited_scan_active_threshold", "300") or "300")
            active_count = repository.active_download_job_count(self.conn)
            if active_count >= threshold:
                return last_result
            result = self.run_next_limited_scan_batch()
            if result is None:
                return last_result
            last_result = result
            if result.get("stopped") or result.get("exhausted") or not result.get("batchMangaIds"):
                return last_result
        return last_result
