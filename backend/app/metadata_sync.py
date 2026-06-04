from __future__ import annotations

import sqlite3
from pathlib import Path

from . import repository


STATUS_MAP = {
    "ongoing": "ONGOING",
    "completed": "ENDED",
    "complete": "ENDED",
    "hiatus": "HIATUS",
    "dropped": "ABANDONED",
    "axed": "ABANDONED",
}


def _genre_names(raw_genres) -> list[str]:
    names: list[str] = []
    for genre in raw_genres or []:
        if isinstance(genre, dict):
            name = genre.get("name") or genre.get("title") or genre.get("slug")
        else:
            name = str(genre)
        if name and name not in names:
            names.append(str(name).strip())
    return [name for name in names if name]


def build_komga_series_metadata(manga: dict, local_title: str | None = None) -> dict:
    tags = ["Source: Asura Scans"]
    if manga.get("asura_type"):
        tags.append(f"Asura: {str(manga['asura_type']).title()}")
    if manga.get("asura_author"):
        tags.append(f"Author: {manga['asura_author']}")
    if manga.get("asura_artist"):
        tags.append(f"Artist: {manga['asura_artist']}")

    payload: dict = {
        "title": manga.get("title") or local_title,
        "titleLock": True,
        "publisher": "Asura Scans",
        "publisherLock": True,
        "genres": _genre_names(manga.get("asura_genres")),
        "genresLock": True,
        "tags": tags,
        "tagsLock": True,
        "links": [{"label": "Asura Scans", "url": manga["url"]}],
        "linksLock": True,
        "language": "en",
        "languageLock": True,
    }
    status = STATUS_MAP.get(str(manga.get("status") or "").lower())
    if status:
        payload["status"] = status
        payload["statusLock"] = True
    if manga.get("remote_chapter_count"):
        payload["totalBookCount"] = int(manga["remote_chapter_count"])
        payload["totalBookCountLock"] = True
    if str(manga.get("asura_type") or "").lower() in {"manhwa", "webtoon"}:
        payload["readingDirection"] = "WEBTOON"
        payload["readingDirectionLock"] = True
    if local_title and local_title != manga.get("title"):
        payload["alternateTitles"] = [{"label": "Local folder title", "title": local_title}]
        payload["alternateTitlesLock"] = True
    return payload


def _verified_local_info(conn: sqlite3.Connection, manga: dict) -> tuple[str | None, str | None, bool]:
    """
    Returns (local_title, folder_name, is_verified).
    - local_title: title to use for metadata and Komga lookup
    - folder_name: the actual folder name on disk (for finding the Komga library)
    - is_verified: False when a pending duplicate blocks sync
    """
    # If the user has explicitly set a folder override (via duplicate resolution), it is verified
    if manga.get("download_folder_override"):
        folder_name = Path(manga["download_folder_override"]).name
        title = manga.get("download_title_override") or folder_name
        return title, folder_name, True

    # Check duplicate candidates for pending blocks
    rows = repository.list_duplicate_candidates(conn)
    for row in rows:
        if row.get("candidate_kind") != "remote_local" or row.get("remote_manga_id") != manga["id"]:
            continue
        local_folder = manga.get("local_folder") or row.get("local_folder") or ""
        folder_name = Path(local_folder).name if local_folder else None
        if row["status"] == "pending":
            return row["local_title"], folder_name, False
        if row["status"] == "confirmed_exists":
            return row["local_title"], folder_name, True
        if row["status"] == "confirmed_new":
            return manga["title"], folder_name, True

    # No duplicate candidates — derive from local_folder
    if manga.get("local_folder"):
        folder_name = Path(manga["local_folder"]).name
        return manga["title"], folder_name, True

    return manga["title"], None, True


def sync_manga_metadata_to_komga(conn: sqlite3.Connection, komga_client, manga_id: int) -> dict:
    manga = repository.get_manga_detail(conn, manga_id)
    if not manga:
        return {"synced": False, "needsReview": False, "error": "manga not found"}

    local_title, folder_name, verified = _verified_local_info(conn, manga)
    if not verified:
        repository.update_manga_metadata_sync_status(
            conn, manga_id, None, "metadata match needs manual duplicate review"
        )
        return {"synced": False, "needsReview": True, "title": manga["title"], "localTitle": local_title}

    if not komga_client.enabled:
        return {"synced": False, "needsReview": False, "error": "Komga is not configured"}

    try:
        series = None

        # Strategy 1: find by actual folder name (handles per-book AND range libraries)
        if folder_name:
            series = komga_client.find_series_for_book(folder_name)

        # Strategy 2: find by local title if different from folder name
        if not series and local_title and local_title != folder_name:
            series = komga_client.find_series_for_book(local_title)

        # Strategy 3: global title search (works after range reorganization)
        if not series and local_title:
            series = komga_client.find_series_by_title(local_title)

        # Strategy 4: fallback to Asura title
        if not series and manga["title"] != local_title:
            series = komga_client.find_series_by_title(manga["title"])

        if not series:
            repository.update_manga_metadata_sync_status(conn, manga_id, None, "Komga series not found")
            return {"synced": False, "needsReview": True, "title": manga["title"], "localTitle": local_title}

        payload = build_komga_series_metadata(manga, local_title=local_title)
        komga_client.update_series_metadata(str(series["id"]), payload)
        repository.update_manga_metadata_sync_status(conn, manga_id, str(series["id"]), None)
        return {"synced": True, "needsReview": False, "seriesId": series["id"], "title": manga["title"]}
    except Exception as exc:
        repository.update_manga_metadata_sync_status(conn, manga_id, None, str(exc))
        raise
