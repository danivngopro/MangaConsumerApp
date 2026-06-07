from __future__ import annotations

import sqlite3
import threading

from . import repository
from .library import scan_library
from .metadata_sync import sync_manga_metadata_to_komga


# ── Full Library Organizer ─────────────────────────────────────────────────────

_ORGANIZE_STEPS = [
    ("dedup_chapters", "Deduplicate chapter files"),
    ("reorganize",     "Reorganize by chapters"),
    ("cleanup",        "Fix Komga libraries"),
    ("deduplicate",    "Deduplicate books"),
    ("komga_scan",     "Komga scan"),
]


class LibraryOrganizer:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._tasks: list[dict] = self._fresh_tasks()
        self._stop_requested = False
        self._sub_progress: dict = {}
        self._started_at: str = ""

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _fresh_tasks(self) -> list[dict]:
        return [
            {"id": tid, "label": label, "status": "pending", "detail": ""}
            for tid, label in _ORGANIZE_STEPS
        ]

    def start(self, *, conn: sqlite3.Connection, settings, komga_client) -> bool:
        with self._lock:
            if self.running:
                return False
            from datetime import datetime, timezone
            self._stop_requested = False
            self._started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            self._tasks = self._fresh_tasks()
            self._sub_progress.clear()
            self._thread = threading.Thread(
                target=self._run,
                kwargs=dict(conn=conn, settings=settings, komga_client=komga_client),
                name="library-full-organize",
                daemon=True,
            )
            self._thread.start()
            return True

    def stop(self) -> None:
        self._stop_requested = True

    def status(self) -> dict:
        return {
            "running": self.running,
            "tasks": list(self._tasks),
            "subProgress": dict(self._sub_progress) if self.running else None,
        }

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

    def _run(self, *, conn: sqlite3.Connection, settings, komga_client) -> None:
        from .library_organizer import (
            deduplicate_chapter_files,
            reorganize_library,
            cleanup_per_book_libraries,
            deduplicate_library,
        )

        # ── Step 0: Deduplicate chapter files ─────────────────────────────────
        self._sub_progress.clear()
        self._set("dedup_chapters", "running", "Scanning for duplicate chapter files…")
        try:
            result = deduplicate_chapter_files(conn, settings.library_root, progress=self._sub_progress)
            detail = f"{result['deleted']} duplicate files removed"
            if result['freedMb']:
                detail += f" · {result['freedMb']} MB freed"
            self._set("dedup_chapters", "done", detail)
        except Exception as exc:
            self._set("dedup_chapters", "error", str(exc))
        if self._stop_requested:
            return self._cancel_remaining()

        # ── Step 1: Reorganize ────────────────────────────────────────────────
        self._sub_progress.clear()
        self._set("reorganize", "running", "Moving books into range folders…")
        try:
            result = reorganize_library(
                conn, settings.library_root, komga_client,
                stop_event=None, progress=self._sub_progress,
            )
            self._set("reorganize", "done", f"{result['moved']} moved · {result['skipped']} already correct")
        except Exception as exc:
            self._set("reorganize", "error", str(exc))
        if self._stop_requested:
            return self._cancel_remaining()

        # ── Step 2: Cleanup ───────────────────────────────────────────────────
        self._sub_progress.clear()
        self._set("cleanup", "running", "Removing per-book Komga libraries…")
        try:
            result = cleanup_per_book_libraries(conn, settings.library_root, komga_client)
            self._set("cleanup", "done", f"{result['deleted']} libraries deleted · {result['komgaScanned']} ranges scanned")
        except Exception as exc:
            self._set("cleanup", "error", str(exc))
        if self._stop_requested:
            return self._cancel_remaining()

        # ── Step 3: Deduplicate ───────────────────────────────────────────────
        self._sub_progress.clear()
        self._set("deduplicate", "running", "Scanning for duplicates…")
        try:
            result = deduplicate_library(
                conn, settings.library_root, komga_client,
                stop_event=None, progress=self._sub_progress,
            )
            detail = f"{result['deleted']} duplicates removed"
            if result['chaptersTransferred']:
                detail += f" · {result['chaptersTransferred']} chapters transferred"
            self._set("deduplicate", "done", detail)
        except Exception as exc:
            self._set("deduplicate", "error", str(exc))
        if self._stop_requested:
            return self._cancel_remaining()

        # ── Step 4: Wait for Komga to finish indexing ─────────────────────────
        import time
        from .library_organizer import RANGE_NAMES

        self._sub_progress.clear()
        if not komga_client.enabled:
            self._set("komga_scan", "done", "Komga not configured — skipped")
        else:
            self._set("komga_scan", "running", "Waiting for Komga to finish indexing…")
            time.sleep(3)  # give Komga a moment to enqueue scan jobs

            timeout_sec = 300
            deadline = time.time() + timeout_sec
            done_count = total_count = 0

            while time.time() < deadline and not self._stop_requested:
                done_count, total_count = komga_client.range_libs_scan_status(
                    set(RANGE_NAMES), self._started_at
                )
                self._sub_progress.update({
                    "total": max(total_count, 1),
                    "processed": done_count,
                    "current": f"{done_count} of {total_count} range libraries indexed",
                })
                if total_count > 0 and done_count >= total_count:
                    break
                time.sleep(5)

            if self._stop_requested:
                self._set("komga_scan", "cancelled", "stopped")
            elif total_count == 0:
                self._set("komga_scan", "done", "No range libraries found in Komga")
            elif done_count >= total_count:
                self._set("komga_scan", "done", f"All {total_count} range libraries indexed")
            else:
                self._set("komga_scan", "done", f"{done_count}/{total_count} indexed (timed out after 5 min)")

        repository.log(conn, "info", "Full library organize complete")


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


# ── Auto Runner ────────────────────────────────────────────────────────────────

_AUTO_RUN_STAGES = [
    ("flush",    "System Flush"),
    ("dedup",    "Scan Local Duplicates"),
    ("organize", "Full Library Organize"),
    ("discover", "Discover Unmatched"),
    ("sync",     "Sync Metadata"),
]


class AutoRunner:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stages: list[dict] = self._fresh_stages()
        self._stop_requested = False
        self._dedup_progress: dict = {}
        self._stop_event = threading.Event()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _fresh_stages(self) -> list[dict]:
        return [
            {"id": sid, "name": name, "status": "pending", "progress": 0}
            for sid, name in _AUTO_RUN_STAGES
        ]

    def start(
        self,
        *,
        flusher,
        organizer,
        conn: sqlite3.Connection,
        settings,
        komga_client,
        download_queue,
        asura_client,
        scan_scheduler,
        scan_stop_event,
    ) -> bool:
        with self._lock:
            if self.running:
                return False
            self._stop_requested = False
            self._stages = self._fresh_stages()
            self._dedup_progress.clear()
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                kwargs=dict(
                    flusher=flusher,
                    organizer=organizer,
                    conn=conn,
                    settings=settings,
                    komga_client=komga_client,
                    download_queue=download_queue,
                    asura_client=asura_client,
                    scan_scheduler=scan_scheduler,
                    scan_stop_event=scan_stop_event,
                ),
                name="auto-runner",
                daemon=True,
            )
            self._thread.start()
            return True

    def stop(self) -> None:
        self._stop_requested = True
        self._stop_event.set()

    def status(self) -> dict:
        stages = []
        for s in self._stages:
            stage = dict(s)
            # Overlay live dedup progress when that stage is actively running
            if stage["id"] == "dedup" and stage["status"] == "running":
                total = self._dedup_progress.get("total", 0)
                processed = self._dedup_progress.get("processed", 0)
                if total:
                    stage["progress"] = round(processed / total * 100)
            stages.append(stage)

        if self.running:
            overall = "running"
        elif any(s["status"] == "error" for s in stages):
            overall = "error"
        elif any(s["status"] in ("done", "cancelled") for s in stages):
            overall = "done"
        else:
            overall = "idle"

        current = next(
            (i + 1 for i, s in enumerate(stages) if s["status"] == "running"), 0
        )
        return {"status": overall, "current_stage": current, "stages": stages}

    def _set(self, stage_id: str, status: str, progress: int = 0) -> None:
        for s in self._stages:
            if s["id"] == stage_id:
                s["status"] = status
                s["progress"] = progress

    def _update_progress(self, stage_id: str, progress: int) -> None:
        for s in self._stages:
            if s["id"] == stage_id:
                s["progress"] = progress

    def _cancel_remaining(self) -> None:
        for s in self._stages:
            if s["status"] == "pending":
                s["status"] = "cancelled"
                s["progress"] = 0

    def _run(
        self,
        *,
        flusher,
        organizer,
        conn: sqlite3.Connection,
        settings,
        komga_client,
        download_queue,
        asura_client,
        scan_scheduler,
        scan_stop_event,
    ) -> None:
        import time
        from .library_organizer import deduplicate_library
        from .metadata_discovery import discover_unmatched_local_metadata

        # ── Stage 1: System Flush ─────────────────────────────────────────────
        self._set("flush", "running", 0)
        started = flusher.start(
            conn=conn,
            settings=settings,
            download_queue=download_queue,
            komga_client=komga_client,
            asura_client=asura_client,
            scan_scheduler=scan_scheduler,
            scan_stop_event=scan_stop_event,
        )
        if not started:
            # Flusher was already running — wait for it to finish first
            while flusher.running and not self._stop_requested:
                time.sleep(1)
            if not flusher.running:
                # It finished before we got to it — treat as already done
                pass
        while flusher.running and not self._stop_requested:
            s = flusher.status()
            tasks = s.get("tasks", [])
            done = sum(1 for t in tasks if t["status"] in ("done", "error", "cancelled"))
            total = len(tasks)
            self._update_progress("flush", round(done / total * 100) if total else 0)
            time.sleep(1)
        if self._stop_requested:
            flusher.stop()
            self._set("flush", "cancelled", 0)
            return self._cancel_remaining()
        flush_tasks = flusher.status().get("tasks", [])
        has_error = any(t["status"] == "error" for t in flush_tasks)
        self._set("flush", "error" if has_error else "done", 0 if has_error else 100)

        if self._stop_requested:
            return self._cancel_remaining()

        # ── Stage 2: Scan Local Duplicates (ignore chapter ranges) ────────────
        self._set("dedup", "running", 0)
        self._dedup_progress.clear()
        try:
            deduplicate_library(
                conn,
                settings.library_root,
                komga_client,
                stop_event=self._stop_event,
                progress=self._dedup_progress,
                ignore_chapter_ranges=True,
            )
            if self._stop_requested:
                self._set("dedup", "cancelled", 0)
            else:
                self._set("dedup", "done", 100)
        except Exception as exc:
            self._set("dedup", "error", 0)
            repository.log(conn, "error", f"Auto-run dedup failed: {exc}")

        if self._stop_requested:
            return self._cancel_remaining()

        # ── Stage 3: Full Library Organize ────────────────────────────────────
        self._set("organize", "running", 0)
        started = organizer.start(conn=conn, settings=settings, komga_client=komga_client)
        if not started:
            while organizer.running and not self._stop_requested:
                time.sleep(1)
        while organizer.running and not self._stop_requested:
            s = organizer.status()
            tasks = s.get("tasks", [])
            done = sum(1 for t in tasks if t["status"] in ("done", "error", "cancelled"))
            total = len(tasks)
            self._update_progress("organize", round(done / total * 100) if total else 0)
            time.sleep(1)
        if self._stop_requested:
            organizer.stop()
            self._set("organize", "cancelled", 0)
            return self._cancel_remaining()
        org_tasks = organizer.status().get("tasks", [])
        has_error = any(t["status"] == "error" for t in org_tasks)
        self._set("organize", "error" if has_error else "done", 0 if has_error else 100)

        if self._stop_requested:
            return self._cancel_remaining()

        # ── Stage 4: Discover Unmatched ───────────────────────────────────────
        self._set("discover", "running", 0)
        try:
            discover_unmatched_local_metadata(conn, asura_client)
            self._set("discover", "done", 100)
        except Exception as exc:
            self._set("discover", "error", 0)
            repository.log(conn, "error", f"Auto-run discover failed: {exc}")

        if self._stop_requested:
            return self._cancel_remaining()

        # ── Stage 5: Sync Metadata ────────────────────────────────────────────
        self._set("sync", "running", 0)
        if not komga_client.enabled:
            self._set("sync", "done", 100)
        else:
            try:
                candidates = repository.metadata_sync_candidates(conn)
                total = len(candidates)
                synced = 0
                for c in candidates:
                    if self._stop_requested:
                        break
                    try:
                        sync_manga_metadata_to_komga(conn, komga_client, int(c["id"]))
                        synced += 1
                    except Exception:
                        pass
                    self._update_progress("sync", round(synced / total * 100) if total else 100)
                if self._stop_requested:
                    self._set("sync", "cancelled", round(synced / total * 100) if total else 0)
                    return self._cancel_remaining()
                self._set("sync", "done", 100)
            except Exception as exc:
                self._set("sync", "error", 0)
                repository.log(conn, "error", f"Auto-run sync failed: {exc}")

        repository.log(conn, "info", "Auto-run complete")
