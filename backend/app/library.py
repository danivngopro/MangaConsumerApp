from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from . import repository
from .duplicates import title_similarity
from .utils import chapter_key, normalize_title


CHAPTER_PATTERNS = [
    re.compile(r"(?:chapter|chap|ch)[\s._-]*(\d+(?:\.\d+)?)", re.IGNORECASE),
    re.compile(r"[\s._-](\d+(?:\.\d+)?)(?:\s*\[[^\]]+\])?\.cbz$", re.IGNORECASE),
]
COMIC_EXTENSIONS = {".cbz", ".cbr", ".zip", ".rar", ".7z", ".epub"}


def extract_chapter_key(filename: str) -> str:
    for pattern in CHAPTER_PATTERNS:
        match = pattern.search(filename)
        if match:
            return chapter_key(match.group(1))
    return ""


def scan_library(conn: sqlite3.Connection, library_root: Path) -> dict:
    if not library_root.exists():
        repository.log(conn, "error", f"Library root does not exist: {library_root}")
        return {"books": 0, "chapters": 0, "error": f"Library root does not exist: {library_root}"}

    repository.clear_inventory(conn)
    book_count = 0
    chapter_count = 0
    folders_seen = 0
    comic_files_seen = 0
    scanned_items: list[dict] = []

    for folder in sorted([item for item in library_root.iterdir() if item.is_dir()]):
        folders_seen += 1
        comic_files = [
            item
            for item in folder.rglob("*")
            if item.is_file() and item.suffix.lower() in COMIC_EXTENSIONS
        ]
        comic_files_seen += len(comic_files)
        if not comic_files:
            continue

        chapters = []
        for comic_file in comic_files:
            key = extract_chapter_key(comic_file.name)
            if key:
                chapters.append(key)

        if not chapters:
            chapters = [str(index + 1) for index, _ in enumerate(comic_files)]

        repository.upsert_inventory(conn, folder.name, str(folder), chapters)
        scanned_items.append(
            {
                "title": folder.name,
                "folder_path": str(folder),
                "chapter_count": len(set(chapters)),
            }
        )
        book_count += 1
        chapter_count += len(set(chapters))

    for index, left in enumerate(scanned_items):
        for right in scanned_items[index + 1:]:
            score, reason = title_similarity(left["title"], right["title"])
            if score < 0.82:
                continue
            keep, delete = left, right
            if int(right["chapter_count"]) > int(left["chapter_count"]):
                keep, delete = right, left
            repository.upsert_local_duplicate_candidate(
                conn,
                keep["title"],
                delete["title"],
                delete["folder_path"],
                int(delete["chapter_count"]),
                int(keep["chapter_count"]),
                score,
                reason,
            )

    repository.log(
        conn,
        "info",
        f"Indexed local library at {library_root}: {book_count}/{folders_seen} folders with comics, {chapter_count} chapters from {comic_files_seen} files",
    )
    return {
        "books": book_count,
        "chapters": chapter_count,
        "error": None,
        "root": str(library_root),
        "foldersSeen": folders_seen,
        "comicFilesSeen": comic_files_seen,
    }


def transfer_chapters(from_folder: Path, to_folder: Path) -> int:
    """Copy chapter files from from_folder to to_folder that don't already exist there. Returns count copied."""
    existing_keys: set[str] = set()
    for f in to_folder.rglob("*"):
        if f.is_file() and f.suffix.lower() in COMIC_EXTENSIONS:
            key = extract_chapter_key(f.name)
            if key:
                existing_keys.add(key)

    import shutil as _shutil

    copied = 0
    for f in sorted(from_folder.rglob("*")):
        if f.is_file() and f.suffix.lower() in COMIC_EXTENSIONS:
            key = extract_chapter_key(f.name)
            if key and key not in existing_keys:
                _shutil.copy2(f, to_folder / f.name)
                existing_keys.add(key)
                copied += 1
    return copied


def local_match_for_title(inventory: dict[str, dict], title: str) -> dict | None:
    normalized = normalize_title(title)
    if normalized in inventory:
        return inventory[normalized]

    for key, item in inventory.items():
        if key == normalized or key in normalized or normalized in key:
            return item
    return None
