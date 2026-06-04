from __future__ import annotations

import sqlite3
import json

from . import repository
from .duplicates import title_similarity
from .utils import normalize_title


AUTO_LINK_THRESHOLD = 0.97
REVIEW_THRESHOLD = 0.82


def _asura_item_to_manga(item: dict) -> dict:
    return {
        "slug": item.get("slug") or normalize_title(str(item.get("title") or "")).replace(" ", "-"),
        "title": item.get("title") or "Untitled",
        "url": item.get("url") or "",
        "cover_url": item.get("cover_url"),
        "status": item.get("status"),
        "remote_chapter_count": int(item.get("chapter_count") or item.get("remote_chapter_count") or 0),
        "type": item.get("type"),
        "author": item.get("author"),
        "artist": item.get("artist"),
        "genres": item.get("genres") or [],
        "rating": item.get("rating"),
        "last_chapter_at": item.get("last_chapter_at"),
        "description": item.get("description"),
    }


def unmatched_local_books(conn: sqlite3.Connection) -> list[dict]:
    items = []
    for row in conn.execute(
            """
            SELECT li.*
            FROM local_inventory li
            LEFT JOIN manga m ON m.normalized_title = li.normalized_title
            WHERE m.id IS NULL
            ORDER BY li.title COLLATE NOCASE
            """
    ).fetchall():
        item = dict(row)
        try:
            item["chapters"] = json.loads(item.pop("chapters_json") or "[]")
        except json.JSONDecodeError:
            item["chapters"] = []
        items.append(item)
    return items


def discover_unmatched_local_metadata(conn: sqlite3.Connection, asura_client, limit: int | None = None) -> dict:
    items = unmatched_local_books(conn)
    if limit:
        items = items[: max(0, int(limit))]

    auto_linked = 0
    review_needed = 0
    skipped = 0
    errors: list[str] = []

    for local in items:
        title = str(local["title"])
        try:
            result = asura_client.search_series(search=title, limit=5, offset=0, sort="title", order="asc")
            candidates = result.get("items") or []
            scored = []
            for candidate in candidates:
                score, reason = title_similarity(str(candidate.get("title") or ""), title)
                if score >= REVIEW_THRESHOLD:
                    scored.append((score, reason, candidate))
            if not scored:
                skipped += 1
                continue

            scored.sort(key=lambda row: row[0], reverse=True)
            score, reason, candidate = scored[0]
            manga_id = repository.upsert_manga(conn, _asura_item_to_manga(candidate))
            remote_count = int(candidate.get("chapter_count") or 0)
            local_count = int(local.get("chapter_count") or 0)

            if score >= AUTO_LINK_THRESHOLD:
                repository.update_manga_scan_counts(
                    conn,
                    manga_id,
                    local_count,
                    max(0, remote_count - local_count),
                    str(local["folder_path"]),
                )
                auto_linked += 1
            else:
                repository.upsert_duplicate_candidate(
                    conn,
                    manga_id,
                    str(candidate.get("title") or ""),
                    title,
                    str(local["folder_path"]),
                    local_count,
                    remote_count,
                    float(score),
                    reason,
                )
                review_needed += 1
        except Exception as exc:
            errors.append(f"{title}: {exc}")

    return {
        "processed": len(items),
        "autoLinked": auto_linked,
        "reviewNeeded": review_needed,
        "skipped": skipped,
        "errors": errors,
    }
