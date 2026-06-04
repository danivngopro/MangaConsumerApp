from __future__ import annotations

import sqlite3
import threading

from . import repository
from .metadata_sync import sync_manga_metadata_to_komga


_TASK_DEFS = [
    ("stop",     "Pause queue & clear pending jobs"),
    ("settings", "Apply recommended settings"),
    ("scan",     "Scan local library + full Asura catalog"),
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
        from .scanner import scan_full_catalog

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
                ("download_concurrency",  "5"),
                ("browser_concurrency",   "3"),
                ("image_download_workers","5"),
                ("auto_scan_every_days",  "0"),
                ("komga_auto_enabled",    "1"),
                ("reorganize_on_drain",   "1"),
            ]:
                repository.set_setting(conn, key, val)
            download_queue.set_concurrency(5)
            download_queue.set_reader_options(3, 5, download_queue.reader_engine)
            # Clear stale metadata sync status so everything re-syncs fresh
            conn.execute("UPDATE manga SET metadata_synced_at = NULL, metadata_last_error = NULL")
            conn.commit()
            self._set("settings", "done", "5 downloads · 3 browser pages · 5 image workers · metadata cleared")
        except Exception as exc:
            self._set("settings", "error", str(exc))
        if self._stop_requested:
            return self._cancel_remaining()

        # ── 3. Full scan (local + Asura) ──────────────────────────────────────
        self._set("scan", "running", "Scanning local library…")
        try:
            scan_stop_event.clear()
            result = scan_full_catalog(
                conn,
                asura_client,
                settings.library_root,
                should_stop=lambda: self._stop_requested,
            )
            if self._stop_requested:
                self._set("scan", "error", f"Stopped — {result['seriesScanned']} series scanned before stop")
            else:
                self._set(
                    "scan", "done",
                    f"{result['seriesScanned']} series · {result['downloadsQueued']} chapters queued",
                )
        except Exception as exc:
            self._set("scan", "error", str(exc))
        if self._stop_requested:
            return self._cancel_remaining()

        # ── 4. Metadata sync ──────────────────────────────────────────────────
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

        # ── 5. Resume ─────────────────────────────────────────────────────────
        self._set("resume", "running")
        try:
            download_queue.resume()
            n = conn.execute(
                "SELECT COUNT(*) AS n FROM jobs WHERE type = 'download' AND status = 'queued'"
            ).fetchone()["n"]
            self._set("resume", "done", f"{n} chapters ready to download")
        except Exception as exc:
            self._set("resume", "error", str(exc))
