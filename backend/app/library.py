from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from . import repository
from .utils import chapter_key, normalize_title


CHAPTER_PATTERNS = [
    re.compile(r"(?:chapter|chap|ch)[\s._-]*(\d+(?:\.\d+)?)", re.IGNORECASE),
    re.compile(r"[\s._-](\d+(?:\.\d+)?)(?:\s*\[[^\]]+\])?\.cbz$", re.IGNORECASE),
]


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

    for folder in sorted([item for item in library_root.iterdir() if item.is_dir()]):
        cbz_files = list(folder.glob("*.cbz"))
        if not cbz_files:
            continue

        chapters = []
        for cbz in cbz_files:
            key = extract_chapter_key(cbz.name)
            if key:
                chapters.append(key)

        if not chapters:
            chapters = [str(index + 1) for index, _ in enumerate(cbz_files)]

        repository.upsert_inventory(conn, folder.name, str(folder), chapters)
        book_count += 1
        chapter_count += len(set(chapters))

    repository.log(conn, "info", f"Indexed local library: {book_count} books, {chapter_count} chapters")
    return {"books": book_count, "chapters": chapter_count, "error": None}


def local_match_for_title(inventory: dict[str, dict], title: str) -> dict | None:
    normalized = normalize_title(title)
    if normalized in inventory:
        return inventory[normalized]

    for key, item in inventory.items():
        if key == normalized or key in normalized or normalized in key:
            return item
    return None
