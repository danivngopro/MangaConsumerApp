from __future__ import annotations

import shutil
import sqlite3
import threading
import time
from pathlib import Path

from . import repository
from .utils import sanitize_filename


CHAPTER_RANGES: list[tuple[int, int | None, str]] = [
    (0, 50, "0-50 Chapters"),
    (50, 100, "50-100 Chapters"),
    (100, 150, "100-150 Chapters"),
    (150, 200, "150-200 Chapters"),
    (200, 250, "200-250 Chapters"),
    (250, 300, "250-300 Chapters"),
    (300, 350, "300-350 Chapters"),
    (350, 400, "350-400 Chapters"),
    (400, 450, "400-450 Chapters"),
    (450, 500, "450-500 Chapters"),
    (500, None, "500+ Chapters"),
]

RANGE_NAMES: frozenset[str] = frozenset(name for _, _, name in CHAPTER_RANGES)


def get_range_name(chapter_count: int) -> str:
    for lo, hi, name in CHAPTER_RANGES:
        if hi is None or chapter_count < hi:
            return name
    return "500+ Chapters"


def cleanup_per_book_libraries(
    conn: sqlite3.Connection,
    library_root: Path,
    komga_client,
) -> dict:
    """
    Delete only ORPHANED per-book Komga libraries — those whose folder no longer exists
    at the top level of library_root (i.e. books that were already moved to a range dir).
    Books still being read at root level are left completely untouched.
    Also creates/scans any range libraries so moved books become visible.
    """
    if not komga_client.enabled:
        return {"error": "Komga not configured", "deleted": 0, "komgaCreated": 0, "komgaScanned": 0, "errors": []}

    try:
        libraries = komga_client.list_libraries()
    except Exception as exc:
        return {"error": f"Could not list Komga libraries: {exc}", "deleted": 0, "komgaCreated": 0, "komgaScanned": 0, "errors": []}

    books_root = komga_client.settings.books_root_docker.rstrip("/")
    range_roots = {f"{books_root}/{sanitize_filename(name)}" for _, _, name in CHAPTER_RANGES}

    deleted = 0
    skipped = 0
    errors: list[str] = []

    for lib in libraries:
        lib_root = (lib.get("root") or "").rstrip("/")
        # Leave range libraries alone
        if lib_root in range_roots:
            continue
        # Only touch libraries under books_root_docker
        prefix = books_root + "/"
        if not lib_root.startswith(prefix):
            continue
        relative = lib_root[len(prefix):]
        # Only per-book libraries have exactly one path component
        if "/" in relative:
            continue
        # If the folder still exists at root level, the user may be reading it — skip
        host_folder = library_root / relative
        if host_folder.exists():
            skipped += 1
            continue
        # Folder is gone (book was moved to a range dir) — safe to delete
        try:
            resp = komga_client.session.delete(f"{komga_client.libraries_url}/{lib['id']}", timeout=30)
            resp.raise_for_status()
            deleted += 1
            repository.log(conn, "info", f"Cleanup: deleted orphaned library '{lib.get('name')}'")
        except Exception as exc:
            errors.append(f"{lib.get('name')}: {exc}")

    # Ensure range libraries exist and scan them so moved books appear
    komga_created = 0
    komga_scanned = 0
    for _, _, range_name in CHAPTER_RANGES:
        range_dir = library_root / range_name
        if not range_dir.exists():
            continue
        try:
            library, created = komga_client.ensure_library_for_book(range_name)
            if created:
                komga_created += 1
                time.sleep(1)
            komga_client.quick_scan_library(str(library["id"]))
            komga_scanned += 1
        except Exception as exc:
            errors.append(f"{range_name}: {exc}")

    repository.log(
        conn, "info",
        f"Komga cleanup: {deleted} orphaned libraries deleted, {skipped} skipped (folder still exists), "
        f"{komga_scanned} range libraries scanned",
    )
    return {
        "deleted": deleted,
        "skipped": skipped,
        "komgaCreated": komga_created,
        "komgaScanned": komga_scanned,
        "errors": errors,
    }


def reorganize_library(
    conn: sqlite3.Connection,
    library_root: Path,
    komga_client,
    stop_event: threading.Event | None = None,
) -> dict:
    if not library_root.exists():
        return {
            "error": f"Library root does not exist: {library_root}",
            "moved": 0,
            "skipped": 0,
            "skippedActive": 0,
            "errors": [],
        }

    # Books with active downloads are left in place this run
    active_manga_ids: set[int] = {
        int(row["manga_id"])
        for row in conn.execute(
            """
            SELECT manga_id FROM jobs
            WHERE type = 'download'
              AND status IN ('queued', 'running')
              AND manga_id IS NOT NULL
            """
        ).fetchall()
    }

    manga_rows = conn.execute(
        """
        SELECT id, title, local_folder, download_folder_override, local_chapter_count
        FROM manga
        WHERE local_folder IS NOT NULL
        """
    ).fetchall()

    moved = 0
    skipped = 0
    skipped_active = 0
    komga_libs_deleted = 0
    errors: list[str] = []

    for row in manga_rows:
        if stop_event and stop_event.is_set():
            break

        if int(row["id"]) in active_manga_ids:
            skipped_active += 1
            continue

        chapter_count = int(row["local_chapter_count"] or 0)
        target_range = get_range_name(chapter_count)

        current_str = row["download_folder_override"] or row["local_folder"]
        if not current_str:
            skipped += 1
            continue

        current = Path(current_str)
        book_name = current.name

        if current.parent == library_root:
            pass  # top-level: needs moving
        elif current.parent.parent == library_root and current.parent.name in RANGE_NAMES:
            if current.parent.name == target_range:
                skipped += 1
                continue
        else:
            # Outside library_root structure — skip
            skipped += 1
            continue

        if not current.exists():
            skipped += 1
            continue

        target = library_root / target_range / book_name
        if target.exists():
            errors.append(f"{book_name}: target already exists at {target}")
            skipped += 1
            continue

        # Delete the per-book Komga library BEFORE moving so Komga removes it cleanly
        # (moving the folder first would leave Komga with a broken/orphaned entry)
        if komga_client.enabled:
            try:
                deleted = komga_client.delete_library_for_book(book_name)
                if deleted:
                    komga_libs_deleted += 1
                    # Clear stale Komga references from DB
                    conn.execute(
                        """
                        UPDATE manga
                        SET komga_library_id = NULL,
                            komga_series_id   = NULL,
                            komga_imported_at = NULL,
                            komga_scanned_at  = NULL,
                            updated_at        = ?
                        WHERE id = ?
                        """,
                        (repository.utc_now(), row["id"]),
                    )
                    conn.commit()
            except Exception as exc:
                repository.log(conn, "warning", f"Could not delete per-book library for '{book_name}': {exc}")

        # Move the folder into the target range directory
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(current), str(target))
            new_str = str(target)
            now = repository.utc_now()
            conn.execute(
                """
                UPDATE manga
                SET local_folder = ?,
                    download_folder_override = CASE WHEN download_folder_override IS NOT NULL THEN ? ELSE NULL END,
                    updated_at = ?
                WHERE id = ?
                """,
                (new_str, new_str, now, row["id"]),
            )
            conn.commit()
            moved += 1
            repository.log(conn, "info", f"Reorganized '{book_name}' → {target_range} ({chapter_count} ch)")
        except Exception as exc:
            errors.append(f"{book_name}: {exc}")
            repository.log(conn, "error", f"Reorganize failed for '{book_name}': {exc}")

    stopped_early = stop_event is not None and stop_event.is_set()

    # Create/update range Komga libraries and scan them (skip if stopped early)
    komga_created = 0
    komga_scanned = 0
    komga_errors: list[str] = []

    if komga_client.enabled and not stopped_early:
        for _, _, range_name in CHAPTER_RANGES:
            range_dir = library_root / range_name
            if not range_dir.exists():
                continue
            try:
                library, created = komga_client.ensure_library_for_book(range_name)
                if created:
                    komga_created += 1
                    time.sleep(1)
                komga_client.quick_scan_library(str(library["id"]))
                komga_scanned += 1
            except Exception as exc:
                komga_errors.append(f"{range_name}: {exc}")

    repository.log(
        conn,
        "info",
        f"Library reorganization: {moved} moved, {skipped} skipped, "
        f"{skipped_active} skipped (active download), "
        f"{komga_libs_deleted} per-book libraries deleted",
    )
    return {
        "moved": moved,
        "skipped": skipped,
        "skippedActive": skipped_active,
        "komgaLibsDeleted": komga_libs_deleted,
        "komgaCreated": komga_created,
        "komgaScanned": komga_scanned,
        "errors": errors,
        "komgaErrors": komga_errors,
    }
