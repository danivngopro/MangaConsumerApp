from __future__ import annotations

import sqlite3
from collections.abc import Callable

from .asura import AsuraClient, AsuraSeries
from .duplicates import best_title_match
from .library import local_match_for_title, scan_library
from . import repository


def scan_full_catalog(
    conn: sqlite3.Connection,
    client: AsuraClient,
    library_root,
    limit: int | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> dict:
    local_result = scan_library(conn, library_root)
    inventory = repository.get_inventory_map(conn)
    series_list = client.crawl_catalog(limit=limit, should_stop=should_stop)
    scanned = 0
    enqueued = 0

    for series_hint in series_list:
        if should_stop and should_stop():
            break
        result = scan_one_series(conn, client, series_hint, inventory, should_stop=should_stop)
        scanned += 1
        enqueued += result["enqueued"]

    scan_name = f"Limited scan ({limit})" if limit else "Full scan"
    stopped = bool(should_stop and should_stop())
    status = "stopped" if stopped else "complete"
    repository.log(conn, "info", f"{scan_name} {status}: {scanned} series, {enqueued} downloads queued")
    return {
        "seriesScanned": scanned,
        "downloadsQueued": enqueued,
        "localBooks": local_result.get("books", 0),
        "localChapters": local_result.get("chapters", 0),
        "stopped": stopped,
    }


def scan_limited_catalog_batch(
    conn: sqlite3.Connection,
    client: AsuraClient,
    library_root,
    batch_size: int,
    offset: int = 0,
    reindex_library: bool = True,
    should_stop: Callable[[], bool] | None = None,
) -> dict:
    if should_stop and should_stop():
        return {
            "seriesScanned": 0,
            "downloadsQueued": 0,
            "localBooks": 0,
            "localChapters": 0,
            "batchMangaIds": [],
            "nextOffset": max(0, int(offset)),
            "catalogTotal": 0,
            "exhausted": False,
            "stopped": True,
            "pendingMangaId": 0,
            "pendingChapterIds": [],
        }
    if reindex_library:
        local_result = scan_library(conn, library_root)
    else:
        local_result = {"books": 0, "chapters": 0, "error": None}
    inventory = repository.get_inventory_map(conn)
    batch_size = max(1, int(batch_size))
    current_offset = max(0, int(offset))
    scanned = 0
    enqueued = 0
    batch_manga_ids: list[int] = []
    total = 0
    pending_manga_id = 0
    pending_chapter_ids: list[int] = []

    stopped = False
    while len(batch_manga_ids) < batch_size:
        if should_stop and should_stop():
            stopped = True
            break
        page_size = min(100, max(24, batch_size * 2))
        try:
            result = client.search_series(limit=page_size, offset=current_offset, sort="latest", order="desc")
        except Exception as exc:
            repository.log(conn, "error", f"Limited scan: catalog fetch failed at offset {current_offset}: {exc}")
            break
        if should_stop and should_stop():
            stopped = True
            break
        items = result.get("items") or []
        total = int(result.get("total") or total or 0)
        if not items:
            break
        current_offset += len(items)

        for item in items:
            if should_stop and should_stop():
                stopped = True
                break
            try:
                hint = AsuraSeries(
                    slug=item["slug"],
                    title=item["title"],
                    url=item["url"],
                    cover_url=item.get("cover_url"),
                    status=item.get("status"),
                    remote_chapter_count=int(item.get("chapter_count") or 0),
                )
                result_item = scan_one_series_deferred(conn, client, hint, inventory, should_stop=should_stop)
                scanned += 1
                missing_count = len(result_item["missingChapterIds"])
                if result_item.get("stopped"):
                    stopped = True
                    break
                if missing_count > 0:
                    batch_manga_ids.append(int(result_item["mangaId"]))
                    if len(batch_manga_ids) >= batch_size:
                        pending_manga_id = int(result_item["mangaId"])
                        pending_chapter_ids = result_item["missingChapterIds"]
                        break
            except Exception as exc:
                repository.log(conn, "error", f"Limited scan failed for {item.get('title', '?')}: {exc}")

        if stopped:
            break
        if current_offset >= total:
            break

    status = "stopped" if stopped else "complete"
    repository.log(
        conn,
        "info",
        f"Limited scan batch {status}: {len(batch_manga_ids)}/{batch_size} books scanned, "
        f"{scanned} series scanned, {pending_manga_id and len(pending_chapter_ids) or 0} pending chapters queued for progressive enqueue, next offset {current_offset}",
    )
    return {
        "seriesScanned": scanned,
        "downloadsQueued": enqueued,
        "localBooks": local_result.get("books", 0),
        "localChapters": local_result.get("chapters", 0),
        "batchMangaIds": batch_manga_ids,
        "nextOffset": current_offset,
        "catalogTotal": total,
        "exhausted": not stopped and (not batch_manga_ids or (total > 0 and current_offset >= total and len(batch_manga_ids) < batch_size)),
        "stopped": stopped,
        "pendingMangaId": pending_manga_id,
        "pendingChapterIds": pending_chapter_ids,
    }


def scan_specific(
    conn: sqlite3.Connection,
    client: AsuraClient,
    library_root,
    query: str,
    priority: int = 0,
    should_stop: Callable[[], bool] | None = None,
) -> dict:
    if should_stop and should_stop():
        return {"mangaId": 0, "title": "", "remoteChapters": 0, "localChapters": 0, "missingChapters": 0, "enqueued": 0, "stopped": True}
    scan_library(conn, library_root)
    inventory = repository.get_inventory_map(conn)
    if should_stop and should_stop():
        return {"mangaId": 0, "title": "", "remoteChapters": 0, "localChapters": 0, "missingChapters": 0, "enqueued": 0, "stopped": True}
    series = client.find_series(query)
    if not series:
        raise ValueError(f"No Asura manga found for: {query}")
    result = scan_one_series(conn, client, series, inventory, priority=priority, should_stop=should_stop)
    repository.log(conn, "info", f"Specific scan complete: {series.title}, {result['enqueued']} downloads queued (priority={priority})")
    return result


def scan_one_series(
    conn: sqlite3.Connection,
    client: AsuraClient,
    series_hint: AsuraSeries,
    inventory: dict[str, dict],
    priority: int = 0,
    should_stop: Callable[[], bool] | None = None,
) -> dict:
    if should_stop and should_stop():
        return {
            "mangaId": 0,
            "title": series_hint.title,
            "remoteChapters": 0,
            "localChapters": 0,
            "missingChapters": 0,
            "enqueued": 0,
            "stopped": True,
        }
    series, chapters = client.fetch_series(series_hint.url)
    if should_stop and should_stop():
        return {
            "mangaId": 0,
            "title": series.title,
            "remoteChapters": len(chapters),
            "localChapters": 0,
            "missingChapters": 0,
            "enqueued": 0,
            "stopped": True,
        }
    manga_id = repository.upsert_manga(
        conn,
        {
            "slug": series.slug,
            "title": series.title,
            "url": series.url,
            "cover_url": series.cover_url or series_hint.cover_url,
            "status": series.status or series_hint.status,
            "remote_chapter_count": series.remote_chapter_count or len(chapters),
            "type": series.type or series_hint.type,
            "author": series.author or series_hint.author,
            "artist": series.artist or series_hint.artist,
            "genres": series.genres or series_hint.genres or [],
            "rating": series.rating or series_hint.rating,
            "last_chapter_at": series.last_chapter_at or series_hint.last_chapter_at,
        },
    )
    repository.upsert_chapters(
        conn,
        manga_id,
        [{"number": ch.number, "label": ch.label, "url": ch.url} for ch in chapters],
    )

    local = local_match_for_title(inventory, series.title)
    duplicate_match = local or best_title_match(series.title, inventory.values())
    if duplicate_match and duplicate_match["title"] == series.title:
        duplicate_match = None
    if duplicate_match:
        existing_candidate = repository.get_duplicate_candidate_for_manga(conn, manga_id, duplicate_match["folder_path"])
        if existing_candidate and existing_candidate.get("status") == "confirmed_exists":
            local = duplicate_match
            repository.set_manga_download_override(conn, manga_id, local["folder_path"], local["title"])
    local_keys = local["chapters"] if local else set()
    missing = repository.find_missing_chapters(conn, manga_id, local_keys)
    duplicate_status = None
    if missing:
        duplicate_status = _handle_duplicate_candidate(
            conn,
            manga_id,
            series.title,
            len(chapters),
            inventory,
            duplicate_match,
        )
        if duplicate_status == "pending":
            repository.update_manga_scan_counts(
                conn,
                manga_id,
                len(local_keys),
                len(missing),
                local["folder_path"] if local else None,
            )
            repository.log(conn, "info", f"Duplicate candidate postponed: {series.title}")
            return {
                "mangaId": manga_id,
                "title": series.title,
                "remoteChapters": len(chapters),
                "localChapters": len(local_keys),
                "missingChapters": len(missing),
                "enqueued": 0,
                "duplicateStatus": "pending",
            }
    for chapter in missing:
        if should_stop and should_stop():
            break
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
        "duplicateStatus": duplicate_status,
    }


def scan_one_series_deferred(
    conn: sqlite3.Connection,
    client: AsuraClient,
    series_hint: AsuraSeries,
    inventory: dict[str, dict],
    should_stop: Callable[[], bool] | None = None,
) -> dict:
    """Scan a series and return missing chapters WITHOUT enqueueing them (for progressive top-up)."""
    if should_stop and should_stop():
        return {
            "mangaId": 0,
            "title": series_hint.title,
            "remoteChapters": 0,
            "localChapters": 0,
            "missingChapterIds": [],
            "stopped": True,
        }
    series, chapters = client.fetch_series(series_hint.url)
    if should_stop and should_stop():
        return {
            "mangaId": 0,
            "title": series.title,
            "remoteChapters": len(chapters),
            "localChapters": 0,
            "missingChapterIds": [],
            "stopped": True,
        }
    manga_id = repository.upsert_manga(
        conn,
        {
            "slug": series.slug,
            "title": series.title,
            "url": series.url,
            "cover_url": series.cover_url or series_hint.cover_url,
            "status": series.status or series_hint.status,
            "remote_chapter_count": series.remote_chapter_count or len(chapters),
            "type": series.type or series_hint.type,
            "author": series.author or series_hint.author,
            "artist": series.artist or series_hint.artist,
            "genres": series.genres or series_hint.genres or [],
            "rating": series.rating or series_hint.rating,
            "last_chapter_at": series.last_chapter_at or series_hint.last_chapter_at,
        },
    )
    repository.upsert_chapters(
        conn,
        manga_id,
        [{"number": ch.number, "label": ch.label, "url": ch.url} for ch in chapters],
    )

    local = local_match_for_title(inventory, series.title)
    duplicate_match = local or best_title_match(series.title, inventory.values())
    if duplicate_match and duplicate_match["title"] == series.title:
        duplicate_match = None
    if duplicate_match:
        existing_candidate = repository.get_duplicate_candidate_for_manga(conn, manga_id, duplicate_match["folder_path"])
        if existing_candidate and existing_candidate.get("status") == "confirmed_exists":
            local = duplicate_match
            repository.set_manga_download_override(conn, manga_id, local["folder_path"], local["title"])
    local_keys = local["chapters"] if local else set()
    missing = repository.find_missing_chapters(conn, manga_id, local_keys)
    duplicate_status = None
    if missing:
        duplicate_status = _handle_duplicate_candidate(
            conn,
            manga_id,
            series.title,
            len(chapters),
            inventory,
            duplicate_match,
        )
        if duplicate_status == "pending":
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
                "missingChapterIds": [],
                "duplicateStatus": "pending",
                "stopped": False,
            }

    missing_chapter_ids = [ch["id"] for ch in missing]

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
        "missingChapterIds": missing_chapter_ids,
        "duplicateStatus": duplicate_status,
        "stopped": False,
    }


def _handle_duplicate_candidate(
    conn: sqlite3.Connection,
    manga_id: int,
    remote_title: str,
    remote_chapter_count: int,
    inventory: dict[str, dict],
    local: dict | None,
) -> str | None:
    match = local or best_title_match(remote_title, inventory.values())
    if not match:
        return None
    if match["title"] == remote_title:
        return None
    candidate = repository.upsert_duplicate_candidate(
        conn,
        manga_id,
        remote_title,
        match["title"],
        match["folder_path"],
        int(match["chapter_count"]),
        remote_chapter_count,
        float(match.get("score", 1.0)),
        str(match.get("reason", "local title match")),
    )
    status = candidate.get("status")
    if status == "confirmed_exists":
        repository.set_manga_download_override(conn, manga_id, match["folder_path"], match["title"])
    return status


def scan_priority_books(
    conn: sqlite3.Connection,
    client: AsuraClient,
    library_root,
    search_kwargs: dict,
    should_stop: Callable[[], bool] | None = None,
) -> dict:
    """Scan only the current Asura search page with priority=1."""
    scan_library(conn, library_root)
    inventory = repository.get_inventory_map(conn)

    result = client.search_series(**search_kwargs)
    items = result.get("items") or []

    scanned = 0
    enqueued = 0
    manga_ids: list[int] = []
    for item in items:
        if should_stop and should_stop():
            break
        try:
            hint = AsuraSeries(
                slug=item["slug"],
                title=item["title"],
                url=item["url"],
                cover_url=item.get("cover_url"),
                status=item.get("status"),
                remote_chapter_count=int(item.get("chapter_count") or 0),
                type=item.get("type"),
                author=item.get("author"),
                artist=item.get("artist"),
                genres=item.get("genres") or [],
                rating=item.get("rating"),
                last_chapter_at=item.get("last_chapter_at"),
            )
            result_item = scan_one_series(conn, client, hint, inventory, priority=1, should_stop=should_stop)
            scanned += 1
            enqueued += result_item["enqueued"]
            if int(result_item["mangaId"]) > 0:
                manga_ids.append(int(result_item["mangaId"]))
        except Exception as exc:
            repository.log(conn, "error", f"Priority scan failed for {item.get('title', '?')}: {exc}")

    repository.log(conn, "info", f"Priority scan complete: {scanned} current-page series, {enqueued} downloads queued at priority=1")
    return {"seriesScanned": scanned, "downloadsQueued": enqueued, "mangaIds": manga_ids}
