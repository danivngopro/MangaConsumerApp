from __future__ import annotations

import shutil
import sqlite3
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


def reorganize_library(
    conn: sqlite3.Connection,
    library_root: Path,
    komga_client,
) -> dict:
    if not library_root.exists():
        return {
            "error": f"Library root does not exist: {library_root}",
            "moved": 0,
            "skipped": 0,
            "errors": [],
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
    errors: list[str] = []

    for row in manga_rows:
        chapter_count = int(row["local_chapter_count"] or 0)
        target_range = get_range_name(chapter_count)

        current_str = row["download_folder_override"] or row["local_folder"]
        if not current_str:
            skipped += 1
            continue

        current = Path(current_str)
        book_name = current.name

        # Determine whether the book is already in a range subdir of library_root
        if current.parent == library_root:
            # Top-level folder: needs moving into range subdir
            pass
        elif current.parent.parent == library_root and current.parent.name in RANGE_NAMES:
            # Already in a range dir
            if current.parent.name == target_range:
                skipped += 1
                continue
        else:
            # Outside library_root structure — skip (could be a custom path)
            skipped += 1
            continue

        if not current.exists():
            skipped += 1
            continue

        target = library_root / target_range / book_name
        if target.exists():
            errors.append(f"{book_name}: target path already exists at {target}")
            skipped += 1
            continue

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

    # Create/update range Komga libraries and scan them
    komga_created = 0
    komga_scanned = 0
    komga_errors: list[str] = []

    if komga_client.enabled:
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

        # Clean up per-book Komga libraries whose folders were moved away
        if moved > 0:
            _delete_orphaned_per_book_libraries(conn, library_root, komga_client)

    repository.log(
        conn,
        "info",
        f"Library reorganization complete: {moved} moved, {skipped} skipped, {len(errors)} errors",
    )
    return {
        "moved": moved,
        "skipped": skipped,
        "errors": errors,
        "komgaCreated": komga_created,
        "komgaScanned": komga_scanned,
        "komgaErrors": komga_errors,
    }


def _delete_orphaned_per_book_libraries(
    conn: sqlite3.Connection,
    library_root: Path,
    komga_client,
) -> None:
    """Delete Komga per-book libraries whose source folders no longer exist at the top level."""
    try:
        libraries = komga_client.list_libraries()
        books_root = komga_client.settings.books_root_docker.rstrip("/")
        range_roots = {f"{books_root}/{sanitize_filename(name)}" for _, _, name in CHAPTER_RANGES}

        for lib in libraries:
            lib_root = (lib.get("root") or "").rstrip("/")
            # Skip range libraries
            if lib_root in range_roots:
                continue
            # Skip anything not under books_root_docker
            prefix = books_root + "/"
            if not lib_root.startswith(prefix):
                continue
            relative = lib_root[len(prefix):]
            # Per-book libraries have exactly one path component (no nested /)
            if "/" in relative:
                continue
            # If the corresponding host folder no longer exists at the top level, delete the library
            host_folder = library_root / relative
            if not host_folder.exists():
                try:
                    resp = komga_client.session.delete(
                        f"{komga_client.libraries_url}/{lib['id']}", timeout=30
                    )
                    resp.raise_for_status()
                    repository.log(conn, "info", f"Deleted orphaned per-book library: {lib.get('name')}")
                except Exception as exc:
                    repository.log(conn, "warning", f"Could not delete library '{lib.get('name')}': {exc}")
    except Exception as exc:
        repository.log(conn, "warning", f"Orphaned library cleanup failed: {exc}")
