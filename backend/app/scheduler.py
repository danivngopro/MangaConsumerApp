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

    def run_full_scan(self, limit: int | None = None) -> dict | None:
        if not self._scan_lock.acquire(blocking=False):
            repository.log(self.conn, "info", "Full scan request ignored because a scan is already running")
            return None
        try:
            result = scan_full_catalog(self.conn, self.client, self.library_root, limit)
            if limit is None:
                repository.set_setting(self.conn, "last_full_scan_at", datetime.now(timezone.utc).isoformat())
            return result
        except Exception as exc:
            repository.log(self.conn, "error", f"Full scan failed: {exc}")
            raise
        finally:
            self._scan_lock.release()

    def start_limited_scan(self, batch_size: int) -> dict | None:
        batch_size = max(1, int(batch_size))
        repository.set_setting(self.conn, "limited_scan_active", "1")
        repository.set_setting(self.conn, "limited_scan_batch_size", str(batch_size))
        repository.set_setting(self.conn, "limited_scan_offset", "0")
        repository.set_json_setting(self.conn, "limited_scan_batch_manga_ids", [])
        repository.log(self.conn, "info", f"Limited scan started with batch size {batch_size}")
        return self.run_next_limited_scan_batch()

    def run_next_limited_scan_batch(self) -> dict | None:
        if not self._scan_lock.acquire(blocking=False):
            repository.log(self.conn, "info", "Limited scan batch request ignored because a scan is already running")
            return None
        try:
            batch_size = int(repository.get_setting(self.conn, "limited_scan_batch_size", "10") or "10")
            offset = int(repository.get_setting(self.conn, "limited_scan_offset", "0") or "0")
            result = scan_limited_catalog_batch(self.conn, self.client, self.library_root, batch_size, offset)
            repository.set_setting(self.conn, "limited_scan_offset", str(result["nextOffset"]))
            repository.set_json_setting(self.conn, "limited_scan_batch_manga_ids", result["batchMangaIds"])
            if not result["batchMangaIds"] or result["exhausted"]:
                repository.set_setting(self.conn, "limited_scan_active", "0")
                repository.log(self.conn, "info", "Limited scan stopped because the Asura catalog has no more books with downloads in range")
            return result
        except Exception as exc:
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
        manga_ids = repository.get_json_setting(self.conn, "limited_scan_batch_manga_ids", [])
        if repository.has_blocking_download_jobs_for_manga_ids(self.conn, manga_ids):
            return
        if not manga_ids:
            return
        repository.log(self.conn, "info", "Limited scan batch fully downloaded; starting next batch")
        self.run_next_limited_scan_batch()
