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


def scan_limited_catalog_batch(
    conn: sqlite3.Connection,
    client: AsuraClient,
    library_root,
    batch_size: int,
    offset: int = 0,
) -> dict:
    local_result = scan_library(conn, library_root)
    inventory = repository.get_inventory_map(conn)
    batch_size = max(1, int(batch_size))
    current_offset = max(0, int(offset))
    scanned = 0
    enqueued = 0
    batch_manga_ids: list[int] = []
    total = 0

    while len(batch_manga_ids) < batch_size:
        page_size = min(100, max(24, batch_size * 2))
        result = client.search_series(limit=page_size, offset=current_offset, sort="latest", order="desc")
        items = result.get("items") or []
        total = int(result.get("total") or total or 0)
        if not items:
            break
        current_offset += len(items)

        for item in items:
            try:
                hint = AsuraSeries(
                    slug=item["slug"],
                    title=item["title"],
                    url=item["url"],
                    cover_url=item.get("cover_url"),
                    status=item.get("status"),
                    remote_chapter_count=int(item.get("chapter_count") or 0),
                )
                result_item = scan_one_series(conn, client, hint, inventory)
                scanned += 1
                enqueued += result_item["enqueued"]
                if result_item["missingChapters"] > 0:
                    batch_manga_ids.append(int(result_item["mangaId"]))
                    if len(batch_manga_ids) >= batch_size:
                        break
            except Exception as exc:
                repository.log(conn, "error", f"Limited scan failed for {item.get('title', '?')}: {exc}")

        if current_offset >= total:
            break

    repository.log(
        conn,
        "info",
        f"Limited scan batch complete: {len(batch_manga_ids)}/{batch_size} books with downloads, "
        f"{scanned} series scanned, {enqueued} downloads queued, next offset {current_offset}",
    )
    return {
        "seriesScanned": scanned,
        "downloadsQueued": enqueued,
        "localBooks": local_result.get("books", 0),
        "localChapters": local_result.get("chapters", 0),
        "batchMangaIds": batch_manga_ids,
        "nextOffset": current_offset,
        "catalogTotal": total,
        "exhausted": not batch_manga_ids or (total > 0 and current_offset >= total and len(batch_manga_ids) < batch_size),
    }


def scan_specific(conn: sqlite3.Connection, client: AsuraClient, library_root, query: str, priority: int = 0) -> dict:
    scan_library(conn, library_root)
    inventory = repository.get_inventory_map(conn)
    series = client.find_series(query)
    if not series:
        raise ValueError(f"No Asura manga found for: {query}")
    result = scan_one_series(conn, client, series, inventory, priority=priority)
    repository.log(conn, "info", f"Specific scan complete: {series.title}, {result['enqueued']} downloads queued (priority={priority})")
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
    """Scan only the current Asura search page with priority=1."""
    scan_library(conn, library_root)
    inventory = repository.get_inventory_map(conn)

    result = client.search_series(**search_kwargs)
    items = result.get("items") or []

    scanned = 0
    enqueued = 0
    manga_ids: list[int] = []
    for item in items:
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
            manga_ids.append(int(result_item["mangaId"]))
        except Exception as exc:
            repository.log(conn, "error", f"Priority scan failed for {item.get('title', '?')}: {exc}")

    repository.log(conn, "info", f"Priority scan complete: {scanned} current-page series, {enqueued} downloads queued at priority=1")
    return {"seriesScanned": scanned, "downloadsQueued": enqueued, "mangaIds": manga_ids}
