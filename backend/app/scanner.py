from __future__ import annotations

import sqlite3

from .asura import AsuraClient, AsuraSeries
from .library import local_match_for_title, scan_library
from . import repository


def scan_full_catalog(conn: sqlite3.Connection, client: AsuraClient, library_root, limit: int | None = None) -> dict:
    local_result = scan_library(conn, library_root)
    inventory = repository.get_inventory_map(conn)
    series_list = client.crawl_catalog(limit=limit)
    scanned = 0
    enqueued = 0

    for series_hint in series_list:
        result = scan_one_series(conn, client, series_hint, inventory)
        scanned += 1
        enqueued += result["enqueued"]

    scan_name = f"Limited scan ({limit})" if limit else "Full scan"
    repository.log(conn, "info", f"{scan_name} complete: {scanned} series, {enqueued} downloads queued")
    return {
        "seriesScanned": scanned,
        "downloadsQueued": enqueued,
        "localBooks": local_result.get("books", 0),
        "localChapters": local_result.get("chapters", 0),
    }


def scan_specific(conn: sqlite3.Connection, client: AsuraClient, library_root, query: str) -> dict:
    scan_library(conn, library_root)
    inventory = repository.get_inventory_map(conn)
    series = client.find_series(query)
    if not series:
        raise ValueError(f"No Asura manga found for: {query}")
    result = scan_one_series(conn, client, series, inventory)
    repository.log(conn, "info", f"Specific scan complete: {series.title}, {result['enqueued']} downloads queued")
    return result


def scan_one_series(
    conn: sqlite3.Connection,
    client: AsuraClient,
    series_hint: AsuraSeries,
    inventory: dict[str, dict],
    priority: int = 0,
) -> dict:
    series, chapters = client.fetch_series(series_hint.url)
    manga_id = repository.upsert_manga(
        conn,
        {
            "slug": series.slug,
            "title": series.title,
            "url": series.url,
            "cover_url": series.cover_url or series_hint.cover_url,
            "status": series.status or series_hint.status,
            "remote_chapter_count": series.remote_chapter_count or len(chapters),
        },
    )
    repository.upsert_chapters(
        conn,
        manga_id,
        [{"number": ch.number, "label": ch.label, "url": ch.url} for ch in chapters],
    )

    local = local_match_for_title(inventory, series.title)
    local_keys = local["chapters"] if local else set()
    missing = repository.find_missing_chapters(conn, manga_id, local_keys)
    for chapter in missing:
        repository.enqueue_download(conn, manga_id, chapter["id"], priority=priority)

    repository.update_manga_scan_counts(
        conn,
        manga_id,
        len(local_keys),
        len(missing),
        local["folder_path"] if local else None,
    )
    return {
        "mangaId": manga_id,
        "title": series.title,
        "remoteChapters": len(chapters),
        "localChapters": len(local_keys),
        "missingChapters": len(missing),
        "enqueued": len(missing),
    }


def scan_priority_books(conn: sqlite3.Connection, client: AsuraClient, library_root, search_kwargs: dict) -> dict:
    """Fetch all pages of an Asura search and scan each book with priority=1."""
    scan_library(conn, library_root)
    inventory = repository.get_inventory_map(conn)

    all_items: list[dict] = []
    offset = 0
    while True:
        result = client.search_series(**{**search_kwargs, "limit": 100, "offset": offset})
        items = result.get("items") or []
        all_items.extend(items)
        total = int(result.get("total") or 0)
        if not items or offset + 100 >= total:
            break
        offset += 100

    scanned = 0
    enqueued = 0
    for item in all_items:
        try:
            hint = AsuraSeries(
                slug=item["slug"],
                title=item["title"],
                url=item["url"],
                cover_url=item.get("cover_url"),
                status=item.get("status"),
                remote_chapter_count=int(item.get("chapter_count") or 0),
            )
            result_item = scan_one_series(conn, client, hint, inventory, priority=1)
            scanned += 1
            enqueued += result_item["enqueued"]
        except Exception as exc:
            repository.log(conn, "error", f"Priority scan failed for {item.get('title', '?')}: {exc}")

    repository.log(conn, "info", f"Priority scan complete: {scanned} series, {enqueued} downloads queued at priority=1")
    return {"seriesScanned": scanned, "downloadsQueued": enqueued}
