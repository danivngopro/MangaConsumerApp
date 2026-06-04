from __future__ import annotations

import sqlite3
import threading

from . import repository
from .library import scan_library
from .metadata_sync import sync_manga_metadata_to_komga


_TASK_DEFS = [
    ("stop",     "Pause queue & clear pending jobs"),
    ("settings", "Apply recommended settings"),
    ("local",    "Scan local library"),
    ("asura",    "Scan full Asura Scans catalog"),
    ("metadata", "Sync Asura metadata to Komga"),
    ("resume",   "Resume download queue"),
]


def _fresh_tasks() -> list[dict]:
    return [{"id": tid, "label": label, "status": "pending", "detail": ""} for tid, label in _TASK_DEFS]


class SystemFlusher:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._tasks: list[dict] = _fresh_tasks()
        self._stop_requested = False

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(
        self,
        *,
        conn: sqlite3.Connection,
        settings,
        download_queue,
        komga_client,
        asura_client,
        scan_scheduler,
        scan_stop_event,
    ) -> bool:
        with self._lock:
            if self.running:
                return False
            self._stop_requested = False
            self._tasks = _fresh_tasks()
            self._thread = threading.Thread(
                target=self._run,
                kwargs=dict(
                    conn=conn,
                    settings=settings,
                    download_queue=download_queue,
                    komga_client=komga_client,
                    asura_client=asura_client,
                    scan_scheduler=scan_scheduler,
                    scan_stop_event=scan_stop_event,
                ),
                name="system-flush",
                daemon=True,
            )
            self._thread.start()
            return True

    def stop(self) -> None:
        self._stop_requested = True

    def status(self) -> dict:
        return {"running": self.running, "tasks": list(self._tasks)}

    def _set(self, task_id: str, status: str, detail: str = "") -> None:
        for t in self._tasks:
            if t["id"] == task_id:
                t["status"] = status
                t["detail"] = detail

    def _cancel_remaining(self) -> None:
        for t in self._tasks:
            if t["status"] == "pending":
                t["status"] = "cancelled"
                t["detail"] = "stopped"

    def _run(
        self,
        *,
        conn: sqlite3.Connection,
        settings,
        download_queue,
        komga_client,
        asura_client,
        scan_scheduler,
        scan_stop_event,
    ) -> None:
        from .scanner import scan_one_series

        # ── 1. Stop active work ───────────────────────────────────────────────
        self._set("stop", "running")
        try:
            scan_stop_event.set()
            scan_scheduler.cancel_current_scan()
            download_queue.pause()
            cleared = conn.execute(
                "DELETE FROM jobs WHERE type = 'download' AND status IN ('queued', 'auto_paused', 'paused')"
            ).rowcount
            conn.commit()
            self._set("stop", "done", f"{cleared} pending jobs cleared")
        except Exception as exc:
            self._set("stop", "error", str(exc))
        if self._stop_requested:
            return self._cancel_remaining()

        # ── 2. Apply settings ─────────────────────────────────────────────────
        self._set("settings", "running")
        try:
            for key, val in [
                ("download_concurrency",   "5"),
                ("browser_concurrency",    "3"),
                ("image_download_workers", "5"),
                ("auto_scan_every_days",   "0"),
                ("komga_auto_enabled",     "1"),
                ("reorganize_on_drain",    "1"),
            ]:
                repository.set_setting(conn, key, val)
            download_queue.set_concurrency(5)
            download_queue.set_reader_options(3, 5, download_queue.reader_engine)
            # Zero out all per-manga counts — the scan will recompute from the filesystem
            conn.execute("UPDATE manga SET missing_count = 0, local_chapter_count = 0")
            # Clear chapter-level download flags so find_missing_chapters uses only
            # the real filesystem (local_keys) instead of stale DB state
            conn.execute("UPDATE chapters SET is_downloaded = 0, file_path = NULL")
            # Clear stale metadata sync status so everything re-syncs fresh
            conn.execute("UPDATE manga SET metadata_synced_at = NULL, metadata_last_error = NULL")
            conn.commit()
            self._set("settings", "done", "5 downloads · 3 browser pages · 5 image workers · counts reset")
        except Exception as exc:
            self._set("settings", "error", str(exc))
        if self._stop_requested:
            return self._cancel_remaining()

        # ── 3. Scan local library ─────────────────────────────────────────────
        self._set("local", "running", "Indexing…")
        inventory: dict = {}
        try:
            result = scan_library(conn, settings.library_root)
            inventory = repository.get_inventory_map(conn)
            self._set(
                "local", "done",
                f"{result['books']} books · {result['chapters']} chapters found",
            )
        except Exception as exc:
            self._set("local", "error", str(exc))
        if self._stop_requested:
            return self._cancel_remaining()

        # ── 4. Full Asura catalog scan ────────────────────────────────────────
        self._set("asura", "running", "Fetching catalog…")
        scan_stop_event.clear()
        series_scanned = 0
        chapters_queued = 0
        try:
            series_list = asura_client.crawl_catalog(should_stop=lambda: self._stop_requested)
            for series_hint in series_list:
                if self._stop_requested:
                    break
                try:
                    r = scan_one_series(
                        conn,
                        asura_client,
                        series_hint,
                        inventory,
                        should_stop=lambda: self._stop_requested,
                    )
                    series_scanned += 1
                    chapters_queued += int(r.get("enqueued", 0))
                except Exception:
                    series_scanned += 1  # count even on per-series error, keep going

                # Update live progress after every series
                self._set(
                    "asura", "running",
                    f"{series_scanned} series scanned · {chapters_queued} chapters queued",
                )

            if self._stop_requested:
                self._set(
                    "asura", "error",
                    f"Stopped — {series_scanned} series · {chapters_queued} chapters queued",
                )
            else:
                self._set(
                    "asura", "done",
                    f"{series_scanned} series · {chapters_queued} chapters queued",
                )
        except Exception as exc:
            self._set("asura", "error", str(exc))
        if self._stop_requested:
            return self._cancel_remaining()

        # ── 5. Metadata sync ──────────────────────────────────────────────────
        self._set("metadata", "running")
        if komga_client.enabled:
            try:
                candidates = repository.metadata_sync_candidates(conn)
                synced = 0
                errors = 0
                for c in candidates:
                    if self._stop_requested:
                        break
                    try:
                        r = sync_manga_metadata_to_komga(conn, komga_client, int(c["id"]))
                        if r.get("synced"):
                            synced += 1
                    except Exception:
                        errors += 1
                self._set("metadata", "done", f"{synced} synced · {errors} errors")
            except Exception as exc:
                self._set("metadata", "error", str(exc))
        else:
            self._set("metadata", "done", "Komga not configured — skipped")
        if self._stop_requested:
            return self._cancel_remaining()

        # ── 6. Resume ─────────────────────────────────────────────────────────
        self._set("resume", "running")
        try:
            download_queue.resume()
            n = conn.execute(
                "SELECT COUNT(*) AS n FROM jobs WHERE type = 'download' AND status = 'queued'"
            ).fetchone()["n"]
            self._set("resume", "done", f"{n} chapters ready to download")
        except Exception as exc:
            self._set("resume", "error", str(exc))
