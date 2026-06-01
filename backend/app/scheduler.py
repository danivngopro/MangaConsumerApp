from __future__ import annotations

import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import repository
from .asura import AsuraClient
from .scanner import scan_full_catalog


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
        threading.Thread(target=lambda: self.run_full_scan(limit), name="manual-full-scan", daemon=True).start()

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

    def _run(self) -> None:
        while not self._stop.is_set():
            interval_days = int(repository.get_setting(self.conn, "auto_scan_every_days", "0") or "0")
            if interval_days > 0 and self._is_due(interval_days):
                try:
                    self.run_full_scan()
                except Exception:
                    pass
            time.sleep(60)

    def _is_due(self, interval_days: int) -> bool:
        last_value = repository.get_setting(self.conn, "last_full_scan_at", "")
        if not last_value:
            return True
        try:
            last = datetime.fromisoformat(last_value)
        except ValueError:
            return True
        return datetime.now(timezone.utc) - last >= timedelta(days=interval_days)
