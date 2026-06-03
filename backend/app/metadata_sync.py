from __future__ import annotations

import sqlite3

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
        "publisher": "Asura Scans",
        "publisherLock": True,
        "genres": _genre_names(manga.get("asura_genres")),
        "genresLock": True,
        "tags": tags,
        "tagsLock": True,
        "links": [{"label": "Asura Scans", "url": manga["url"]}],
        "linksLock": True,
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


def _verified_local_title(conn: sqlite3.Connection, manga: dict) -> tuple[str | None, bool]:
    rows = repository.list_duplicate_candidates(conn)
    for row in rows:
        if row.get("candidate_kind") != "remote_local" or row.get("remote_manga_id") != manga["id"]:
            continue
        if row["status"] == "pending":
            return row["local_title"], False
        if row["status"] == "confirmed_exists":
            return row["local_title"], True
        if row["status"] == "confirmed_new":
            return manga["title"], True
    if manga.get("download_title_override"):
        return manga["download_title_override"], True
    if manga.get("local_folder"):
        return manga["title"], True
    return manga["title"], True


def sync_manga_metadata_to_komga(conn: sqlite3.Connection, komga_client, manga_id: int) -> dict:
    manga = repository.get_manga_detail(conn, manga_id)
    if not manga:
        return {"synced": False, "needsReview": False, "error": "manga not found"}
    local_title, verified = _verified_local_title(conn, manga)
    if not verified:
        repository.update_manga_metadata_sync_status(conn, manga_id, None, "metadata match needs manual duplicate review")
        return {"synced": False, "needsReview": True, "title": manga["title"], "localTitle": local_title}
    if not komga_client.enabled:
        return {"synced": False, "needsReview": False, "error": "Komga is not configured"}
    try:
        series = komga_client.find_series_for_book(local_title or manga["title"])
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
