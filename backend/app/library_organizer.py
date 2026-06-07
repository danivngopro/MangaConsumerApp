from __future__ import annotations

import shutil
import sqlite3
import threading
import time
from pathlib import Path

from . import repository
from .duplicates import title_similarity
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


def deduplicate_chapter_files(
    conn: sqlite3.Connection,
    library_root: Path,
    progress: dict | None = None,
) -> dict:
    """
    Within each book folder, remove duplicate chapter files — keeping the largest
    file per unique chapter key. This runs before reorganize so that chapter counts
    are accurate for range assignment.
    """
    from .library import _iter_book_folders, extract_chapter_key, COMIC_EXTENSIONS

    all_folders = list(_iter_book_folders(library_root))
    if progress is not None:
        progress.update({"total": len(all_folders), "processed": 0, "deleted": 0, "current": ""})

    total_deleted = 0
    total_bytes = 0
    errors: list[str] = []

    for idx, folder in enumerate(all_folders):
        if progress is not None:
            progress["current"] = folder.name
            progress["processed"] = idx

        comic_files = [
            f for f in folder.rglob("*")
            if f.is_file() and f.suffix.lower() in COMIC_EXTENSIONS
        ]

        # Group files by chapter key; files with no parseable key are left alone
        by_key: dict[str, list[Path]] = {}
        for f in comic_files:
            key = extract_chapter_key(f.name)
            if key:
                by_key.setdefault(key, []).append(f)

        book_deleted = 0
        for key, dupes in by_key.items():
            if len(dupes) <= 1:
                continue
            # Keep the largest file (highest quality), delete the rest
            dupes.sort(key=lambda f: f.stat().st_size, reverse=True)
            for dup in dupes[1:]:
                try:
                    size = dup.stat().st_size
                    dup.unlink()
                    book_deleted += 1
                    total_bytes += size
                except Exception as exc:
                    errors.append(f"{folder.name}/{dup.name}: {exc}")

        if book_deleted:
            total_deleted += book_deleted
            if progress is not None:
                progress["deleted"] = total_deleted
            repository.log(
                conn, "info",
                f"Removed {book_deleted} duplicate chapter files from '{folder.name}'",
            )

    if progress is not None:
        progress["processed"] = len(all_folders)

    freed_mb = round(total_bytes / 1_048_576, 1)
    repository.log(
        conn, "info",
        f"Chapter dedup: {total_deleted} duplicate files removed, {freed_mb} MB freed",
    )
    return {"deleted": total_deleted, "freedMb": freed_mb, "errors": errors}


def cleanup_per_book_libraries(
    conn: sqlite3.Connection,
    library_root: Path,
    komga_client,
) -> dict:
    """
    Delete ALL per-book Komga libraries (any library under books_root_docker that is not
    a range library). Then create/scan range libraries so books remain accessible.
    """
    if not komga_client.enabled:
        return {"error": "Komga not configured", "deleted": 0, "komgaCreated": 0, "komgaScanned": 0, "errors": []}

    try:
        komga_by_root = komga_client.list_libraries_by_root()
    except Exception as exc:
        return {"error": f"Could not list Komga libraries: {exc}", "deleted": 0, "komgaCreated": 0, "komgaScanned": 0, "errors": []}

    books_root = komga_client.settings.books_root_docker.rstrip("/")
    range_roots = {f"{books_root}/{sanitize_filename(name)}" for _, _, name in CHAPTER_RANGES}

    deleted = 0
    errors: list[str] = []

    for lib in list(komga_by_root.values()):
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
        try:
            resp = komga_client.session.delete(f"{komga_client.libraries_url}/{lib['id']}", timeout=30)
            resp.raise_for_status()
            deleted += 1
            repository.log(conn, "info", f"Cleanup: deleted per-book library '{lib.get('name')}'")
        except Exception as exc:
            errors.append(f"{lib.get('name')}: {exc}")

    # Ensure range libraries exist and scan them — use the already-fetched dict
    komga_created = 0
    komga_scanned = 0
    for _, _, range_name in CHAPTER_RANGES:
        range_dir = library_root / range_name
        range_dir.mkdir(parents=True, exist_ok=True)
        docker_root = komga_client.docker_root_for_book(range_name)
        existing = komga_by_root.get(docker_root)
        try:
            if existing:
                lib_id = str(existing["id"])
            else:
                payload = {
                    "name": komga_client.sanitize_name(range_name),
                    "root": docker_root,
                    "importComicInfoBook": True,
                    "importComicInfoSeries": True,
                    "importComicInfoCollection": True,
                    "importEpubBook": True,
                    "importEpubSeries": True,
                    "scanForceModifiedTime": True,
                    "repairExtensions": True,
                    "convertToCbz": True,
                    "emptyTrashAfterScan": True,
                    "scanOnStartup": False,
                }
                resp = komga_client.session.post(komga_client.libraries_url, json=payload, timeout=30)
                resp.raise_for_status()
                lib_id = str(resp.json()["id"])
                komga_created += 1
                time.sleep(1)
            komga_client.quick_scan_library(lib_id)
            komga_scanned += 1
        except Exception as exc:
            errors.append(f"{range_name}: {exc}")

    repository.log(
        conn, "info",
        f"Komga cleanup: {deleted} per-book libraries deleted, {komga_scanned} range libraries scanned",
    )
    return {
        "deleted": deleted,
        "komgaCreated": komga_created,
        "komgaScanned": komga_scanned,
        "errors": errors,
    }


def reorganize_library(
    conn: sqlite3.Connection,
    library_root: Path,
    komga_client,
    stop_event: threading.Event | None = None,
    progress: dict | None = None,
) -> dict:
    from .library import _iter_book_folders, extract_chapter_key, COMIC_EXTENSIONS

    if not library_root.exists():
        return {
            "error": f"Library root does not exist: {library_root}",
            "moved": 0, "skipped": 0, "skippedActive": 0,
            "komgaLibsDeleted": 0, "komgaCreated": 0, "komgaScanned": 0,
            "errors": [], "komgaErrors": [],
        }

    # Folders with active downloads are untouchable
    active_folders: set[Path] = set()
    for row in conn.execute(
        """
        SELECT m.local_folder FROM manga m
        JOIN jobs j ON j.manga_id = m.id
        WHERE j.status IN ('queued', 'running') AND m.local_folder IS NOT NULL
        """
    ).fetchall():
        if row["local_folder"]:
            active_folders.add(Path(row["local_folder"]))

    # Walk the filesystem directly — no dependency on manga.local_folder being set
    all_folders = list(_iter_book_folders(library_root))

    moved = 0
    skipped = 0
    skipped_active = 0
    komga_libs_deleted = 0
    errors: list[str] = []

    if progress is not None:
        progress.update({"total": len(all_folders), "processed": 0, "moved": 0, "current": ""})

    # Pre-fetch all Komga libraries ONCE
    komga_by_root: dict[str, dict] = {}
    if komga_client.enabled:
        try:
            komga_by_root = komga_client.list_libraries_by_root()
        except Exception as exc:
            repository.log(conn, "warning", f"Could not pre-fetch Komga libraries: {exc}")

    for folder in all_folders:
        if stop_event and stop_event.is_set():
            break

        if progress is not None:
            progress["current"] = folder.name
            progress["processed"] = moved + skipped + skipped_active

        if folder in active_folders:
            skipped_active += 1
            continue

        comic_files = [
            f for f in folder.rglob("*")
            if f.is_file() and f.suffix.lower() in COMIC_EXTENSIONS
        ]
        chapter_keys: set[str] = set()
        for cf in comic_files:
            key = extract_chapter_key(cf.name)
            if key:
                chapter_keys.add(key)
        chapter_count = len(chapter_keys) if chapter_keys else len(comic_files)

        target_range = get_range_name(chapter_count)

        # Already in the right range folder → skip
        if folder.parent.name in RANGE_NAMES:
            if folder.parent.name == target_range:
                skipped += 1
                continue
        elif folder.parent != library_root:
            # Unexpected nesting — skip
            skipped += 1
            continue

        target = library_root / target_range / folder.name
        if target.exists():
            repository.log(
                conn, "warning",
                f"Reorganize collision: '{folder.name}' should move to {target_range} "
                f"but target already exists ({chapter_count} files). Run Deduplicate to merge.",
            )
            skipped += 1
            continue

        # Delete the per-book Komga library BEFORE moving
        if komga_client.enabled:
            docker_root = komga_client.docker_root_for_book(folder.name)
            lib = komga_by_root.get(docker_root)
            if lib:
                try:
                    resp = komga_client.session.delete(f"{komga_client.libraries_url}/{lib['id']}", timeout=30)
                    resp.raise_for_status()
                    komga_by_root.pop(docker_root, None)
                    komga_libs_deleted += 1
                    conn.execute(
                        """
                        UPDATE manga
                        SET komga_library_id = NULL,
                            komga_series_id   = NULL,
                            komga_imported_at = NULL,
                            komga_scanned_at  = NULL,
                            updated_at        = ?
                        WHERE local_folder = ? OR download_folder_override = ?
                        """,
                        (repository.utc_now(), str(folder), str(folder)),
                    )
                    conn.commit()
                except Exception as exc:
                    repository.log(conn, "warning", f"Could not delete per-book library for '{folder.name}': {exc}")

        # Move the folder
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(folder), str(target))
            new_str = str(target)
            now = repository.utc_now()
            conn.execute(
                """
                UPDATE manga
                SET local_folder = ?,
                    download_folder_override = CASE WHEN download_folder_override IS NOT NULL THEN ? ELSE NULL END,
                    updated_at = ?
                WHERE local_folder = ? OR download_folder_override = ?
                """,
                (new_str, new_str, now, str(folder), str(folder)),
            )
            conn.commit()
            moved += 1
            if progress is not None:
                progress["moved"] = moved
            repository.log(conn, "info", f"Reorganized '{folder.name}' → {target_range} ({chapter_count} ch)")
        except Exception as exc:
            errors.append(f"{folder.name}: {exc}")
            repository.log(conn, "error", f"Reorganize failed for '{folder.name}': {exc}")

    stopped_early = stop_event is not None and stop_event.is_set()

    # Create/update range Komga libraries and scan them
    komga_created = 0
    komga_scanned = 0
    komga_errors: list[str] = []

    if komga_client.enabled and not stopped_early:
        for _, _, range_name in CHAPTER_RANGES:
            range_dir = library_root / range_name
            range_dir.mkdir(parents=True, exist_ok=True)
            docker_root = komga_client.docker_root_for_book(range_name)
            existing = komga_by_root.get(docker_root)
            try:
                if existing:
                    lib_id = str(existing["id"])
                else:
                    payload = {
                        "name": komga_client.sanitize_name(range_name),
                        "root": docker_root,
                        "importComicInfoBook": True,
                        "importComicInfoSeries": True,
                        "importComicInfoCollection": True,
                        "importEpubBook": True,
                        "importEpubSeries": True,
                        "scanForceModifiedTime": True,
                        "repairExtensions": True,
                        "convertToCbz": True,
                        "emptyTrashAfterScan": True,
                        "scanOnStartup": False,
                    }
                    resp = komga_client.session.post(komga_client.libraries_url, json=payload, timeout=30)
                    resp.raise_for_status()
                    lib_id = str(resp.json()["id"])
                    komga_created += 1
                    time.sleep(1)
                komga_client.quick_scan_library(lib_id)
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


def deduplicate_library(
    conn: sqlite3.Connection,
    library_root: Path,
    komga_client,
    stop_event: threading.Event | None = None,
    threshold: float = 0.82,
    progress: dict | None = None,
) -> dict:
    """
    Find all books with similar titles across all range directories and root level.
    Keep the copy with the most chapters (transferring unique chapters from others first),
    then delete the duplicate folders and their per-book Komga libraries.
    """
    from .library import _iter_book_folders, extract_chapter_key, COMIC_EXTENSIONS

    # Collect all book folders with chapter counts
    books: list[dict] = []
    for folder in _iter_book_folders(library_root):
        comic_files = [
            f for f in folder.rglob("*")
            if f.is_file() and f.suffix.lower() in COMIC_EXTENSIONS
        ]
        chapter_keys: list[str] = []
        for cf in comic_files:
            key = extract_chapter_key(cf.name)
            if key:
                chapter_keys.append(key)
        if not chapter_keys:
            chapter_keys = [str(i + 1) for i, _ in enumerate(comic_files)]
        books.append({
            "title": folder.name,
            "folder": folder,
            "chapter_count": len(set(chapter_keys)),
        })

    n = len(books)

    if progress is not None:
        progress.update({"phase": "comparing", "total": n, "processed": 0, "deleted": 0, "current": ""})

    # Union-find to cluster similar titles
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        parent[find(x)] = find(y)

    for i in range(n):
        if stop_event and stop_event.is_set():
            break
        if progress is not None:
            progress["processed"] = i
            progress["current"] = books[i]["title"]
        for j in range(i + 1, n):
            score, _ = title_similarity(books[i]["title"], books[j]["title"])
            if score >= threshold:
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    # Folders with active downloads are untouchable
    active_folders: set[Path] = set()
    for row in conn.execute(
        """
        SELECT m.local_folder FROM manga m
        JOIN jobs j ON j.manga_id = m.id
        WHERE j.status IN ('queued', 'running') AND m.local_folder IS NOT NULL
        """
    ).fetchall():
        if row["local_folder"]:
            active_folders.add(Path(row["local_folder"]))

    deleted = 0
    chapters_transferred = 0
    skipped_active = 0
    errors: list[str] = []

    if progress is not None:
        progress["phase"] = "deleting"
        progress["processed"] = n

    for group_indices in groups.values():
        if len(group_indices) <= 1:
            continue
        if stop_event and stop_event.is_set():
            break

        group = [books[i] for i in group_indices]

        if any(b["folder"] in active_folders for b in group):
            skipped_active += len(group) - 1
            continue

        # Keep the book with the most chapters; break ties by preferring shorter folder name
        group.sort(key=lambda b: (-b["chapter_count"], len(b["title"])))
        keeper = group[0]
        duplicates = group[1:]

        for dup in duplicates:
            # Transfer chapters the keeper is missing before deleting
            if dup["folder"].exists() and keeper["folder"].exists():
                try:
                    from .library import transfer_chapters
                    transferred = transfer_chapters(dup["folder"], keeper["folder"])
                    chapters_transferred += transferred
                except Exception as exc:
                    repository.log(conn, "warning", f"Chapter transfer {dup['folder'].name} → {keeper['folder'].name}: {exc}")

            # Remove per-book Komga library (no-op if already in a range lib)
            if komga_client.enabled:
                try:
                    komga_client.delete_library_for_book(dup["folder"].name)
                except Exception:
                    pass

            # Delete the folder
            try:
                if dup["folder"].exists():
                    shutil.rmtree(dup["folder"])
                    deleted += 1
                    if progress is not None:
                        progress["deleted"] = deleted
                        progress["current"] = dup["folder"].name
                    repository.log(
                        conn, "info",
                        f"Dedup: deleted '{dup['folder'].name}' ({dup['chapter_count']} ch) "
                        f"→ kept '{keeper['folder'].name}' ({keeper['chapter_count']} ch)",
                    )
            except Exception as exc:
                errors.append(f"{dup['folder'].name}: {exc}")

            # Clear stale DB reference
            try:
                conn.execute(
                    "UPDATE manga SET local_folder = NULL, download_folder_override = NULL, updated_at = ? WHERE local_folder = ?",
                    (repository.utc_now(), str(dup["folder"])),
                )
            except Exception:
                pass

        conn.commit()

    # Rescan range libraries so Komga reflects the deletions
    if komga_client.enabled and not (stop_event and stop_event.is_set()):
        for _, _, range_name in CHAPTER_RANGES:
            range_dir = library_root / range_name
            if not range_dir.exists():
                continue
            try:
                library, created = komga_client.ensure_library_for_book(range_name)
                if created:
                    time.sleep(1)
                komga_client.quick_scan_library(str(library["id"]))
            except Exception as exc:
                errors.append(f"scan {range_name}: {exc}")

    repository.log(
        conn, "info",
        f"Dedup: {deleted} duplicate folders deleted, {chapters_transferred} chapters transferred, "
        f"{skipped_active} skipped (active download)",
    )
    return {
        "deleted": deleted,
        "chaptersTransferred": chapters_transferred,
        "skippedActive": skipped_active,
        "errors": errors,
    }
