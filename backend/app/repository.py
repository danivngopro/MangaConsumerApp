from __future__ import annotations

import json
import sqlite3
import threading
from typing import Iterable

from .utils import chapter_key, fix_mojibake, normalize_title, utc_now

DB_LOCK = threading.RLock()


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def clean_row(row: sqlite3.Row | dict) -> dict:
    item = dict(row)
    for key in ("title", "manga_title", "label", "chapter_label"):
        if item.get(key):
            item[key] = fix_mojibake(item[key])
    return item


def clean_manga_row(row: sqlite3.Row | dict) -> dict:
    item = clean_row(row)
    try:
        item["asura_genres"] = json.loads(item.get("asura_genres_json") or "[]")
    except json.JSONDecodeError:
        item["asura_genres"] = []
    item.pop("asura_genres_json", None)
    return item


def log(conn: sqlite3.Connection, level: str, message: str) -> None:
    with DB_LOCK:
        conn.execute(
            "INSERT INTO logs(level, message, created_at) VALUES (?, ?, ?)",
            (level, message, utc_now()),
        )
        conn.commit()


def get_setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO settings(key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )
    conn.commit()


def get_json_setting(conn: sqlite3.Connection, key: str, default):
    value = get_setting(conn, key, "")
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def set_json_setting(conn: sqlite3.Connection, key: str, value) -> None:
    set_setting(conn, key, json.dumps(value))


def _set_setting_uncommitted(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO settings(key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def active_download_job_count(conn: sqlite3.Connection) -> int:
    # Only count jobs that will actually be worked on: queued, running, and
    # auto_paused (which will resume when priority jobs finish). Excludes
    # 'failed' (permanently stuck) and 'paused' (manually blocked) so the
    # top-up threshold isn't inflated by dead/stalled jobs.
    row = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM jobs
        WHERE type = 'download'
          AND status IN ('queued', 'running', 'auto_paused')
        """
    ).fetchone()
    return int(row["count"] or 0)


def unresolved_download_job_count(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM jobs
        WHERE type = 'download'
          AND status IN ('queued', 'running', 'auto_paused', 'paused', 'failed')
        """
    ).fetchone()
    return int(row["count"] or 0)


def start_limited_scan_state(conn: sqlite3.Connection, active_threshold: int) -> bool:
    with DB_LOCK:
        try:
            conn.rollback()
        except Exception:
            pass
        conn.execute("BEGIN IMMEDIATE")
        try:
            is_active = get_setting(conn, "limited_scan_active", "0") == "1"
            if get_setting(conn, "limited_scan_batch_running", "0") == "1":
                if is_active:
                    _set_setting_uncommitted(conn, "limited_scan_active_threshold", str(max(1, int(active_threshold))))
                    conn.commit()
                    return True
                conn.execute("ROLLBACK")
                return False
            _set_setting_uncommitted(conn, "limited_scan_active", "1")
            _set_setting_uncommitted(conn, "limited_scan_active_threshold", str(max(1, int(active_threshold))))
            if not is_active:
                _set_setting_uncommitted(conn, "limited_scan_offset", "0")
                _set_setting_uncommitted(conn, "limited_scan_batch_manga_ids", "[]")
            _set_setting_uncommitted(conn, "limited_scan_batch_running", "0")
            conn.commit()
            return True
        except Exception:
            conn.execute("ROLLBACK")
            raise


def set_limited_scan_threshold(conn: sqlite3.Connection, active_threshold: int) -> int:
    threshold = max(1, int(active_threshold))
    set_setting(conn, "limited_scan_active_threshold", str(threshold))
    return threshold


def claim_limited_scan_batch(conn: sqlite3.Connection) -> tuple[int, int] | None:
    with DB_LOCK:
        try:
            conn.rollback()
        except Exception:
            pass
        conn.execute("BEGIN IMMEDIATE")
        try:
            if get_setting(conn, "limited_scan_active", "0") != "1":
                conn.execute("ROLLBACK")
                return None
            if get_setting(conn, "limited_scan_batch_running", "0") == "1":
                conn.execute("ROLLBACK")
                return None
            active_threshold = int(get_setting(conn, "limited_scan_active_threshold", "300") or "300")
            active_count = active_download_job_count(conn)
            if active_count >= active_threshold:
                conn.execute("ROLLBACK")
                return None
            offset = int(get_setting(conn, "limited_scan_offset", "0") or "0")
            _set_setting_uncommitted(conn, "limited_scan_batch_running", "1")
            conn.commit()
            return max(1, active_threshold), max(0, offset)
        except Exception:
            conn.execute("ROLLBACK")
            raise


def finish_limited_scan_batch(conn: sqlite3.Connection, result: dict) -> None:
    with DB_LOCK:
        try:
            conn.rollback()
        except Exception:
            pass
        conn.execute("BEGIN IMMEDIATE")
        try:
            _set_setting_uncommitted(conn, "limited_scan_offset", str(result["nextOffset"]))
            _set_setting_uncommitted(
                conn,
                "limited_scan_batch_manga_ids",
                json.dumps(result["batchMangaIds"]),
            )
            if result.get("pendingMangaId"):
                _set_setting_uncommitted(conn, "limited_scan_pending_manga_id", str(result["pendingMangaId"]))
                _set_setting_uncommitted(conn, "limited_scan_pending_chapter_ids", json.dumps(result.get("pendingChapterIds", [])))
                _set_setting_uncommitted(conn, "limited_scan_pending_chapter_index", "0")
            _set_setting_uncommitted(conn, "limited_scan_batch_running", "0")
            if result.get("stopped"):
                _set_setting_uncommitted(conn, "limited_scan_active", "0")
                _set_setting_uncommitted(conn, "limited_scan_batch_manga_ids", "[]")
                _set_setting_uncommitted(conn, "limited_scan_pending_manga_id", "0")
            elif not result["batchMangaIds"] or result["exhausted"]:
                _set_setting_uncommitted(conn, "limited_scan_offset", "0")
                _set_setting_uncommitted(conn, "limited_scan_batch_manga_ids", "[]")
                _set_setting_uncommitted(conn, "limited_scan_pending_manga_id", "0")
            conn.commit()
        except Exception:
            conn.execute("ROLLBACK")
            raise


def stop_limited_scan_state(conn: sqlite3.Connection) -> None:
    with DB_LOCK:
        conn.execute("BEGIN IMMEDIATE")
        try:
            _set_setting_uncommitted(conn, "limited_scan_active", "0")
            _set_setting_uncommitted(conn, "limited_scan_batch_manga_ids", "[]")
            _set_setting_uncommitted(conn, "limited_scan_batch_running", "0")
            conn.commit()
        except Exception:
            conn.execute("ROLLBACK")
            raise


def upsert_inventory(
    conn: sqlite3.Connection,
    title: str,
    folder_path: str,
    chapters: Iterable[str],
) -> None:
    keys = sorted({chapter_key(ch) for ch in chapters if chapter_key(ch)}, key=lambda v: float(v))
    conn.execute(
        """
        INSERT INTO local_inventory(
            normalized_title, title, folder_path, chapter_count, chapters_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(normalized_title) DO UPDATE SET
            title = excluded.title,
            folder_path = excluded.folder_path,
            chapter_count = excluded.chapter_count,
            chapters_json = excluded.chapters_json,
            updated_at = excluded.updated_at
        """,
        (
            normalize_title(title),
            title,
            folder_path,
            len(keys),
            json.dumps(keys),
            utc_now(),
        ),
    )
    conn.commit()


def clear_inventory(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM local_inventory")
    conn.commit()


def remove_inventory_entry(conn: sqlite3.Connection, title: str) -> None:
    conn.execute("DELETE FROM local_inventory WHERE normalized_title = ?", (normalize_title(title),))
    conn.commit()


def get_inventory_map(conn: sqlite3.Connection) -> dict[str, dict]:
    rows = conn.execute("SELECT * FROM local_inventory").fetchall()
    result: dict[str, dict] = {}
    for row in rows:
        item = dict(row)
        item["chapters"] = set(json.loads(item.pop("chapters_json") or "[]"))
        result[item["normalized_title"]] = item
    return result


def get_inventory_items(conn: sqlite3.Connection) -> list[dict]:
    return list(get_inventory_map(conn).values())


def upsert_manga(conn: sqlite3.Connection, manga: dict) -> int:
    now = utc_now()
    title = fix_mojibake(manga["title"])
    normalized = normalize_title(title)
    conn.execute(
        """
        INSERT INTO manga(
            slug, title, normalized_title, url, cover_url, status,
            remote_chapter_count, asura_type, asura_author, asura_artist,
            asura_genres_json, asura_rating, asura_last_chapter_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(slug) DO UPDATE SET
            title = excluded.title,
            normalized_title = excluded.normalized_title,
            url = excluded.url,
            cover_url = excluded.cover_url,
            status = excluded.status,
            remote_chapter_count = excluded.remote_chapter_count,
            asura_type = COALESCE(excluded.asura_type, asura_type),
            asura_author = COALESCE(excluded.asura_author, asura_author),
            asura_artist = COALESCE(excluded.asura_artist, asura_artist),
            asura_genres_json = CASE WHEN excluded.asura_genres_json != '[]' THEN excluded.asura_genres_json ELSE asura_genres_json END,
            asura_rating = COALESCE(excluded.asura_rating, asura_rating),
            asura_last_chapter_at = COALESCE(excluded.asura_last_chapter_at, asura_last_chapter_at),
            updated_at = excluded.updated_at
        """,
        (
            manga["slug"],
            title,
            normalized,
            manga["url"],
            manga.get("cover_url"),
            manga.get("status"),
            int(manga.get("remote_chapter_count") or 0),
            manga.get("type") or manga.get("asura_type"),
            manga.get("author") or manga.get("asura_author"),
            manga.get("artist") or manga.get("asura_artist"),
            json.dumps(manga.get("genres") or manga.get("asura_genres") or []),
            manga.get("rating") or manga.get("asura_rating"),
            manga.get("last_chapter_at") or manga.get("asura_last_chapter_at"),
            now,
        ),
    )
    row = conn.execute("SELECT id FROM manga WHERE slug = ?", (manga["slug"],)).fetchone()
    return int(row["id"])


def update_manga_scan_counts(
    conn: sqlite3.Connection,
    manga_id: int,
    local_count: int,
    missing_count: int,
    local_folder: str | None,
) -> None:
    conn.execute(
        """
        UPDATE manga
        SET local_chapter_count = ?, missing_count = ?, local_folder = ?,
            last_scanned_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (local_count, missing_count, local_folder, utc_now(), utc_now(), manga_id),
    )
    conn.commit()


def set_manga_download_override(conn: sqlite3.Connection, manga_id: int, folder: str | None, title: str | None) -> None:
    conn.execute(
        """
        UPDATE manga
        SET download_folder_override = ?,
            download_title_override = ?,
            local_folder = COALESCE(?, local_folder),
            updated_at = ?
        WHERE id = ?
        """,
        (folder, title, folder, utc_now(), manga_id),
    )
    conn.commit()


def update_manga_metadata_sync_status(conn: sqlite3.Connection, manga_id: int, series_id: str | None, error: str | None) -> None:
    conn.execute(
        """
        UPDATE manga
        SET komga_series_id = COALESCE(?, komga_series_id),
            metadata_synced_at = CASE WHEN ? IS NULL THEN ? ELSE metadata_synced_at END,
            metadata_last_error = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (series_id, error, utc_now(), error, utc_now(), manga_id),
    )
    conn.commit()


def metadata_sync_candidates(conn: sqlite3.Connection) -> list[dict]:
    return [
        clean_manga_row(row)
        for row in conn.execute(
            """
            SELECT *
            FROM manga
            WHERE local_folder IS NOT NULL
               OR download_folder_override IS NOT NULL
               OR COALESCE(asura_genres_json, '[]') != '[]'
               OR asura_type IS NOT NULL
               OR asura_author IS NOT NULL
               OR asura_artist IS NOT NULL
            ORDER BY
                CASE WHEN metadata_last_error IS NOT NULL THEN 0 ELSE 1 END,
                COALESCE(metadata_synced_at, '') ASC,
                title COLLATE NOCASE
            """
        ).fetchall()
    ]


def upsert_chapters(conn: sqlite3.Connection, manga_id: int, chapters: Iterable[dict]) -> None:
    now = utc_now()
    chapters_list = []
    for chapter in chapters:
        key = chapter_key(chapter["number"])
        if not key:
            continue
        chapters_list.append((
            manga_id,
            key,
            chapter.get("label") or f"Chapter {key}",
            chapter["url"],
            now,
        ))

    if not chapters_list:
        return

    placeholders = ",".join("(?, ?, ?, ?, ?)" for _ in chapters_list)
    values = []
    for chapter_tuple in chapters_list:
        values.extend(chapter_tuple)

    conn.execute(
        f"""
        INSERT INTO chapters(manga_id, chapter_key, label, url, updated_at)
        VALUES {placeholders}
        ON CONFLICT(manga_id, chapter_key) DO UPDATE SET
            label = excluded.label,
            url = excluded.url,
            updated_at = excluded.updated_at
        """,
        values,
    )
    conn.commit()


def mark_downloaded(conn: sqlite3.Connection, chapter_id: int, file_path: str) -> None:
    conn.execute(
        "UPDATE chapters SET is_downloaded = 1, file_path = ?, updated_at = ? WHERE id = ?",
        (file_path, utc_now(), chapter_id),
    )
    conn.commit()


def find_missing_chapters(conn: sqlite3.Connection, manga_id: int, local_keys: set[str]) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM chapters WHERE manga_id = ? ORDER BY CAST(chapter_key AS REAL)",
        (manga_id,),
    ).fetchall()
    missing = []
    for row in rows:
        item = dict(row)
        if item["chapter_key"] not in local_keys and not item["is_downloaded"]:
            missing.append(item)
    return missing


def enqueue_download(conn: sqlite3.Connection, manga_id: int, chapter_id: int, priority: int = 0) -> None:
    existing = conn.execute(
        """
        SELECT id, priority, status FROM jobs
        WHERE type = 'download'
          AND chapter_id = ?
          AND status IN ('queued', 'running', 'paused', 'auto_paused', 'failed')
        ORDER BY
          CASE status
            WHEN 'queued' THEN 0
            WHEN 'running' THEN 1
            WHEN 'auto_paused' THEN 2
            WHEN 'paused' THEN 3
            ELSE 4
          END,
          id ASC
        LIMIT 1
        """,
        (chapter_id,),
    ).fetchone()
    if existing:
        updates: list[str] = []
        values: list[object] = []
        if priority > int(existing["priority"] or 0):
            updates.append("priority = ?")
            values.append(priority)
        if priority > 0 and existing["status"] in {"paused", "auto_paused"}:
            updates.append("status = 'queued'")
        if updates:
            values.append(existing["id"])
            conn.execute(f"UPDATE jobs SET {', '.join(updates)} WHERE id = ?", values)
            conn.commit()
        return
    conn.execute(
        """
        INSERT INTO jobs(type, status, manga_id, chapter_id, priority, created_at)
        VALUES ('download', 'queued', ?, ?, ?, ?)
        """,
        (manga_id, chapter_id, priority, utc_now()),
    )
    conn.commit()


def claim_next_download_job(conn: sqlite3.Connection) -> dict | None:
    with DB_LOCK:
        row = conn.execute(
            """
            SELECT * FROM jobs
            WHERE type = 'download' AND status = 'queued'
            ORDER BY priority DESC, id ASC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE jobs SET status = 'running', attempts = attempts + 1, started_at = ?, error = NULL WHERE id = ?",
            (utc_now(), row["id"]),
        )
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM jobs WHERE id = ?", (row["id"],)).fetchone())


def set_job_status(conn: sqlite3.Connection, job_id: int, status: str, error: str | None = None) -> None:
    with DB_LOCK:
        if status == "running":
            conn.execute(
                "UPDATE jobs SET status = ?, attempts = attempts + 1, started_at = ?, error = NULL WHERE id = ?",
                (status, utc_now(), job_id),
            )
        elif status in {"done", "failed", "skipped"}:
            conn.execute(
                "UPDATE jobs SET status = ?, error = ?, finished_at = ? WHERE id = ?",
                (status, error, utc_now(), job_id),
            )
        else:
            conn.execute("UPDATE jobs SET status = ?, error = ? WHERE id = ?", (status, error, job_id))
        conn.commit()


def get_download_target(conn: sqlite3.Connection, job_id: int) -> tuple[dict, dict]:
    row = conn.execute(
        """
        SELECT
            j.id AS job_id,
            m.id AS manga_id,
            m.title AS manga_title,
            m.url AS manga_url,
            m.local_folder AS local_folder,
            m.download_folder_override AS download_folder_override,
            m.download_title_override AS download_title_override,
            c.id AS chapter_id,
            c.chapter_key,
            c.label,
            c.url AS chapter_url
        FROM jobs j
        JOIN manga m ON m.id = j.manga_id
        JOIN chapters c ON c.id = j.chapter_id
        WHERE j.id = ?
        """,
        (job_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Download job {job_id} no longer has a valid manga/chapter target")
    data = dict(row)
    return (
        {
            "id": data["manga_id"],
            "title": data["manga_title"],
            "url": data["manga_url"],
            "local_folder": data["local_folder"],
            "download_folder": data["download_folder_override"] or data["local_folder"],
            "download_title": data["download_title_override"] or data["manga_title"],
        },
        {
            "id": data["chapter_id"],
            "chapter_key": data["chapter_key"],
            "label": data["label"],
            "url": data["chapter_url"],
        },
    )


def has_pending_download_jobs_for_manga(conn: sqlite3.Connection, manga_id: int) -> bool:
    row = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM jobs
        WHERE type = 'download'
          AND manga_id = ?
          AND status IN ('queued', 'running', 'failed')
        """,
        (manga_id,),
    ).fetchone()
    return int(row["count"]) > 0


def has_blocking_download_jobs_for_manga_ids(conn: sqlite3.Connection, manga_ids: list[int]) -> bool:
    ids = [int(manga_id) for manga_id in manga_ids if int(manga_id) > 0]
    if not ids:
        return False
    placeholders = ",".join("?" for _ in ids)
    row = conn.execute(
        f"""
        SELECT COUNT(*) AS count
        FROM jobs
        WHERE type = 'download'
          AND manga_id IN ({placeholders})
          AND status IN ('queued', 'running', 'failed', 'paused', 'auto_paused')
        """,
        ids,
    ).fetchone()
    return int(row["count"]) > 0


def download_now_atomic(conn: sqlite3.Connection, manga_id: int) -> tuple[int, int]:
    """Atomically pause all other queued jobs and elevate this manga to priority=2.
    Returns (paused_count, upgraded_count). Done under a single lock to avoid
    the race where maybe_resume_auto_paused runs between the two steps."""
    with DB_LOCK:
        paused = conn.execute(
            """UPDATE jobs SET status = 'auto_paused'
               WHERE type = 'download' AND status = 'queued'
               AND manga_id != ?""",
            (manga_id,),
        ).rowcount
        upgraded = conn.execute(
            """UPDATE jobs SET priority = 2, status = 'queued'
               WHERE type = 'download' AND manga_id = ?
               AND status IN ('queued', 'auto_paused')""",
            (manga_id,),
        ).rowcount
        conn.commit()
        return paused, upgraded


def maybe_resume_auto_paused(conn: sqlite3.Connection) -> int:
    """If no priority>=1 jobs remain queued or running, resume all auto-paused jobs."""
    with DB_LOCK:
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM jobs WHERE type = 'download' AND priority >= 1 AND status IN ('queued', 'running')"
        ).fetchone()
        if int(row["count"]) > 0:
            return 0
        cursor = conn.execute(
            "UPDATE jobs SET status = 'queued' WHERE status = 'auto_paused'"
        )
        conn.commit()
        return cursor.rowcount


def maybe_enqueue_next_pending_chapter(conn: sqlite3.Connection) -> bool:
    """If there are pending chapters from top-up, enqueue the next one.
    Returns True if a chapter was enqueued, False otherwise."""
    with DB_LOCK:
        pending_manga_id_str = get_setting(conn, "limited_scan_pending_manga_id", "0")
        pending_manga_id = int(pending_manga_id_str or "0")
        if pending_manga_id <= 0:
            return False

        pending_ids_str = get_setting(conn, "limited_scan_pending_chapter_ids", "[]")
        pending_ids = json.loads(pending_ids_str or "[]")
        if not pending_ids:
            _set_setting_uncommitted(conn, "limited_scan_pending_manga_id", "0")
            conn.commit()
            return False

        pending_index_str = get_setting(conn, "limited_scan_pending_chapter_index", "0")
        pending_index = int(pending_index_str or "0")
        if pending_index >= len(pending_ids):
            _set_setting_uncommitted(conn, "limited_scan_pending_manga_id", "0")
            _set_setting_uncommitted(conn, "limited_scan_pending_chapter_ids", "[]")
            _set_setting_uncommitted(conn, "limited_scan_pending_chapter_index", "0")
            conn.commit()
            return False

        chapter_id = int(pending_ids[pending_index])
        _set_setting_uncommitted(conn, "limited_scan_pending_chapter_index", str(pending_index + 1))
        conn.commit()

        enqueue_download(conn, pending_manga_id, chapter_id, priority=0)
        return True


def pause_downloads_for_manga(conn: sqlite3.Connection, manga_id: int) -> int:
    with DB_LOCK:
        cursor = conn.execute(
            """
            UPDATE jobs
            SET status = 'paused'
            WHERE type = 'download' AND manga_id = ? AND status = 'queued'
            """,
            (manga_id,),
        )
        conn.commit()
        return cursor.rowcount


def pause_downloads_except_manga_ids(conn: sqlite3.Connection, manga_ids: list[int]) -> int:
    ids = [int(manga_id) for manga_id in manga_ids if int(manga_id) > 0]
    with DB_LOCK:
        if not ids:
            cursor = conn.execute(
                """
                UPDATE jobs
                SET status = 'paused'
                WHERE type = 'download' AND status IN ('queued', 'auto_paused')
                """
            )
        else:
            placeholders = ",".join("?" for _ in ids)
            cursor = conn.execute(
                f"""
                UPDATE jobs
                SET status = 'paused'
                WHERE type = 'download' AND status IN ('queued', 'auto_paused')
                  AND manga_id NOT IN ({placeholders})
                """,
                ids,
            )
        conn.commit()
        return cursor.rowcount


def resume_downloads_for_manga(conn: sqlite3.Connection, manga_id: int) -> int:
    with DB_LOCK:
        cursor = conn.execute(
            """
            UPDATE jobs
            SET status = 'queued'
            WHERE type = 'download' AND manga_id = ? AND status = 'paused'
            """,
            (manga_id,),
        )
        conn.commit()
        return cursor.rowcount


def enqueue_all_missing(conn: sqlite3.Connection) -> int:
    """Bulk-enqueue every chapter that is not downloaded and has no active job."""
    with DB_LOCK:
        now = utc_now()
        cursor = conn.execute(
            """
            INSERT INTO jobs(type, status, manga_id, chapter_id, priority, created_at)
            SELECT 'download', 'queued', c.manga_id, c.id, 0, ?
            FROM chapters c
            WHERE c.is_downloaded = 0
              AND NOT EXISTS (
                SELECT 1 FROM duplicate_candidates dc
                WHERE dc.remote_manga_id = c.manga_id
                  AND dc.status = 'pending'
              )
              AND NOT EXISTS (
                SELECT 1 FROM jobs j
                WHERE j.type = 'download'
                  AND j.chapter_id = c.id
                  AND j.status IN ('queued', 'running', 'paused', 'auto_paused', 'failed')
              )
            """,
            (now,),
        )
        conn.commit()
        return cursor.rowcount


def upsert_duplicate_candidate(
    conn: sqlite3.Connection,
    manga_id: int,
    remote_title: str,
    local_title: str,
    local_folder: str,
    local_chapter_count: int,
    remote_chapter_count: int,
    score: float,
    reason: str,
) -> dict:
    now = utc_now()
    with DB_LOCK:
        existing = conn.execute(
            """
            SELECT id, status FROM duplicate_candidates
            WHERE candidate_kind = 'remote_local'
              AND remote_manga_id = ?
              AND local_folder = ?
            """,
            (manga_id, local_folder),
        ).fetchone()
        if existing:
            next_status = existing["status"] if existing["status"] in {"confirmed_exists", "confirmed_new", "ignored"} else "pending"
            conn.execute(
                """
                UPDATE duplicate_candidates
                SET remote_title = ?,
                    local_title = ?,
                    local_chapter_count = ?,
                    remote_chapter_count = ?,
                    score = ?,
                    reason = ?,
                    status = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (remote_title, local_title, local_chapter_count, remote_chapter_count, score, reason, next_status, now, existing["id"]),
            )
        else:
            conn.execute(
                """
                INSERT INTO duplicate_candidates(
                    candidate_kind, remote_manga_id, remote_title, local_title, local_folder,
                    local_chapter_count, remote_chapter_count, score, reason,
                    status, created_at, updated_at
                )
                VALUES ('remote_local', ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (manga_id, remote_title, local_title, local_folder, local_chapter_count, remote_chapter_count, score, reason, now, now),
            )
        conn.commit()
    return get_duplicate_candidate_for_manga(conn, manga_id, local_folder) or {}


def get_duplicate_candidate_for_manga(conn: sqlite3.Connection, manga_id: int, local_folder: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM duplicate_candidates WHERE candidate_kind = 'remote_local' AND remote_manga_id = ? AND local_folder = ?",
        (manga_id, local_folder),
    ).fetchone()
    return clean_row(row) if row else None


def upsert_local_duplicate_candidate(
    conn: sqlite3.Connection,
    keep_title: str,
    keep_folder: str,
    delete_title: str,
    delete_folder: str,
    delete_chapter_count: int,
    keep_chapter_count: int,
    score: float,
    reason: str,
) -> None:
    now = utc_now()
    with DB_LOCK:
        existing = conn.execute(
            """
            SELECT id FROM duplicate_candidates
            WHERE candidate_kind = 'local_local'
              AND remote_title = ?
              AND local_folder = ?
            """,
            (keep_title, delete_folder),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE duplicate_candidates
                SET local_title = ?,
                    remote_folder = ?,
                    local_chapter_count = ?,
                    remote_chapter_count = ?,
                    score = ?,
                    reason = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (delete_title, keep_folder, delete_chapter_count, keep_chapter_count, score, reason, now, existing["id"]),
            )
        else:
            conn.execute(
                """
                INSERT INTO duplicate_candidates(
                    candidate_kind, remote_manga_id, remote_title, remote_folder,
                    local_title, local_folder, local_chapter_count, remote_chapter_count,
                    score, reason, status, created_at, updated_at
                )
                VALUES ('local_local', NULL, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (keep_title, keep_folder, delete_title, delete_folder, delete_chapter_count, keep_chapter_count, score, reason, now, now),
            )
        conn.commit()


def list_duplicate_candidates(conn: sqlite3.Connection) -> list[dict]:
    return [
        clean_row(row)
        for row in conn.execute(
            """
            SELECT dc.*, m.local_folder AS remote_local_folder,
                   m.download_folder_override, m.download_title_override
            FROM duplicate_candidates dc
            LEFT JOIN manga m ON m.id = dc.remote_manga_id
            ORDER BY
                CASE dc.status
                    WHEN 'pending' THEN 0
                    WHEN 'confirmed_exists' THEN 1
                    WHEN 'confirmed_new' THEN 2
                    ELSE 3
                END,
                dc.score DESC,
                dc.updated_at DESC
            """
        ).fetchall()
    ]


def resolve_duplicate_candidate(conn: sqlite3.Connection, candidate_id: int, status: str) -> dict:
    if status not in {"confirmed_exists", "confirmed_new", "ignored"}:
        raise ValueError("invalid duplicate status")
    with DB_LOCK:
        row = conn.execute("SELECT * FROM duplicate_candidates WHERE id = ?", (candidate_id,)).fetchone()
        if row is None:
            raise ValueError("duplicate candidate not found")
        candidate = dict(row)
        now = utc_now()
        if candidate.get("candidate_kind") == "local_local":
            conn.execute(
                "UPDATE duplicate_candidates SET status = ?, resolved_at = ?, updated_at = ? WHERE id = ?",
                (status, now, now, candidate_id),
            )
            conn.commit()
            return {"candidateId": candidate_id, "status": status, "enqueued": 0}
        conn.execute(
            "UPDATE duplicate_candidates SET status = ?, resolved_at = ?, updated_at = ? WHERE id = ?",
            (status, now, now, candidate_id),
        )
        if status == "confirmed_exists":
            conn.execute(
                """
                UPDATE manga
                SET download_folder_override = ?,
                    download_title_override = ?,
                    local_folder = ?,
                    local_chapter_count = ?,
                    missing_count = MAX(0, remote_chapter_count - ?),
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    candidate["local_folder"],
                    candidate["local_title"],
                    candidate["local_folder"],
                    int(candidate["local_chapter_count"] or 0),
                    int(candidate["local_chapter_count"] or 0),
                    now,
                    candidate["remote_manga_id"],
                ),
            )
        elif status == "confirmed_new":
            conn.execute(
                """
                UPDATE manga
                SET download_folder_override = NULL,
                    download_title_override = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (now, candidate["remote_manga_id"]),
            )
        conn.commit()

    enqueued = 0
    if status in {"confirmed_exists", "confirmed_new"}:
        manga = conn.execute("SELECT * FROM manga WHERE id = ?", (candidate["remote_manga_id"],)).fetchone()
        if manga:
            local_keys = set()
            if status == "confirmed_exists":
                inventory = get_inventory_map(conn)
                local = inventory.get(normalize_title(candidate["local_title"]))
                if local:
                    local_keys = local["chapters"]
            missing = find_missing_chapters(conn, int(candidate["remote_manga_id"]), local_keys)
            for chapter in missing:
                enqueue_download(conn, int(candidate["remote_manga_id"]), int(chapter["id"]))
                enqueued += 1
    return {"candidateId": candidate_id, "status": status, "enqueued": enqueued}


def reset_missing_chapters(conn: sqlite3.Connection) -> dict:
    """Clear stale missing/download state so the next full scan recalculates it."""
    with DB_LOCK:
        removed = conn.execute(
            """
            DELETE FROM jobs
            WHERE type = 'download'
              AND status IN ('queued', 'paused', 'auto_paused', 'failed', 'done', 'skipped')
            """
        ).rowcount
        chapters = conn.execute(
            """
            UPDATE chapters
            SET is_downloaded = 0,
                file_path = NULL,
                updated_at = ?
            WHERE is_downloaded != 0 OR file_path IS NOT NULL
            """,
            (utc_now(),),
        ).rowcount
        manga = conn.execute(
            """
            UPDATE manga
            SET local_chapter_count = 0,
                missing_count = 0,
                local_folder = NULL,
                last_scanned_at = NULL,
                updated_at = ?
            WHERE local_chapter_count != 0
               OR missing_count != 0
               OR local_folder IS NOT NULL
               OR last_scanned_at IS NOT NULL
            """,
            (utc_now(),),
        ).rowcount
        _set_setting_uncommitted(conn, "limited_scan_active", "0")
        _set_setting_uncommitted(conn, "limited_scan_batch_manga_ids", "[]")
        _set_setting_uncommitted(conn, "limited_scan_batch_running", "0")
        conn.commit()
        return {"mangaReset": manga, "chaptersReset": chapters, "jobsRemoved": removed}


def delete_queued_downloads(conn: sqlite3.Connection, zero_percent_only: bool = False) -> int:
    with DB_LOCK:
        if zero_percent_only:
            cursor = conn.execute(
                """
                DELETE FROM jobs
                WHERE type = 'download'
                  AND status IN ('queued', 'paused', 'auto_paused')
                  AND COALESCE(manga_id, 0) IN (
                    SELECT m.id
                    FROM manga m
                    WHERE COALESCE(m.local_chapter_count, 0) = 0
                      AND NOT EXISTS (
                        SELECT 1
                        FROM chapters c
                        WHERE c.manga_id = m.id
                          AND c.is_downloaded = 1
                      )
                      AND NOT EXISTS (
                        SELECT 1
                        FROM jobs started
                        WHERE started.type = 'download'
                          AND started.manga_id = m.id
                          AND started.status IN ('running', 'done', 'failed')
                      )
                  )
                """
            )
        else:
            cursor = conn.execute(
                """
                DELETE FROM jobs
                WHERE type = 'download' AND status IN ('queued', 'paused', 'auto_paused')
                """
            )
        conn.commit()
        return cursor.rowcount


def retry_failed_downloads(conn: sqlite3.Connection, manga_id: int | None = None) -> int:
    with DB_LOCK:
        if manga_id is None:
            cursor = conn.execute(
                """
                UPDATE jobs
                SET status = 'queued', attempts = 0, error = NULL, started_at = NULL, finished_at = NULL
                WHERE type = 'download' AND status = 'failed'
                """
            )
        else:
            cursor = conn.execute(
                """
                UPDATE jobs
                SET status = 'queued', attempts = 0, error = NULL, started_at = NULL, finished_at = NULL
                WHERE type = 'download' AND status = 'failed' AND manga_id = ?
                """,
                (manga_id,),
            )
        conn.commit()
        return cursor.rowcount


def requeue_interrupted_downloads(conn: sqlite3.Connection) -> int:
    with DB_LOCK:
        cursor = conn.execute(
            """
            UPDATE jobs
            SET status = 'queued',
                error = 'Requeued after backend restart',
                started_at = NULL
            WHERE type = 'download' AND status = 'running'
            """
        )
        conn.commit()
        return cursor.rowcount


def manga_has_paused_jobs(conn: sqlite3.Connection, manga_id: int) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) AS count FROM jobs WHERE type = 'download' AND manga_id = ? AND status = 'paused'",
        (manga_id,),
    ).fetchone()
    return int(row["count"]) > 0


def update_komga_status(
    conn: sqlite3.Connection,
    manga_id: int,
    library_id: str | None,
    imported: bool,
    scanned: bool,
    error: str | None,
) -> None:
    with DB_LOCK:
        row = conn.execute("SELECT komga_imported_at FROM manga WHERE id = ?", (manga_id,)).fetchone()
        imported_at = utc_now() if imported and row and not row["komga_imported_at"] else (row["komga_imported_at"] if row else None)
        scanned_at = utc_now() if scanned else None
        conn.execute(
            """
            UPDATE manga
            SET komga_library_id = COALESCE(?, komga_library_id),
                komga_imported_at = COALESCE(?, komga_imported_at),
                komga_scanned_at = COALESCE(?, komga_scanned_at),
                komga_last_error = ?
            WHERE id = ?
            """,
            (library_id, imported_at, scanned_at, error, manga_id),
        )
        conn.commit()


def list_recent_logs(conn: sqlite3.Connection, limit: int = 100) -> list[dict]:
    return [
        dict(row)
        for row in conn.execute(
            "SELECT id, level, message, created_at FROM logs ORDER BY id DESC LIMIT ?",
            (max(1, min(500, int(limit))),),
        ).fetchall()
    ]


def list_manga(conn: sqlite3.Connection) -> list[dict]:
    return [
        clean_manga_row(row)
        for row in conn.execute(
            """
            SELECT * FROM manga
            ORDER BY missing_count DESC, title COLLATE NOCASE
            """
        ).fetchall()
    ]


def get_manga_detail(conn: sqlite3.Connection, manga_id: int) -> dict | None:
    manga_row = conn.execute("SELECT * FROM manga WHERE id = ?", (manga_id,)).fetchone()
    manga = clean_manga_row(manga_row) if manga_row else None
    if manga is None:
        return None
    chapters = [
        clean_row(row)
        for row in conn.execute(
            """
            SELECT * FROM chapters
            WHERE manga_id = ?
            ORDER BY CAST(chapter_key AS REAL)
            """,
            (manga_id,),
        ).fetchall()
    ]
    jobs = [
        clean_row(row)
        for row in conn.execute(
            """
            SELECT j.*, c.label AS chapter_label
            FROM jobs j
            LEFT JOIN chapters c ON c.id = j.chapter_id
            WHERE j.manga_id = ?
            ORDER BY j.id DESC
            LIMIT 200
            """,
            (manga_id,),
        ).fetchall()
    ]
    downloaded_count = conn.execute(
        "SELECT COUNT(*) AS count FROM chapters WHERE manga_id = ? AND is_downloaded = 1",
        (manga_id,),
    ).fetchone()["count"]
    inventory = conn.execute(
        "SELECT chapters_json FROM local_inventory WHERE normalized_title = ?",
        (manga["normalized_title"],),
    ).fetchone()
    local_chapters = json.loads(inventory["chapters_json"] or "[]") if inventory else []
    existing_count = int(manga["local_chapter_count"] or 0)
    remote_count = int(manga["remote_chapter_count"] or len(chapters) or 0)
    available_count = min(remote_count, existing_count + int(downloaded_count)) if remote_count else existing_count + int(downloaded_count)
    manga["chapters"] = chapters
    manga["local_chapters"] = local_chapters
    manga["jobs"] = jobs
    manga["downloaded_count"] = available_count
    manga["existing_downloaded_count"] = existing_count
    manga["newly_downloaded_count"] = int(downloaded_count)
    manga["paused_downloads"] = manga_has_paused_jobs(conn, manga_id)
    return manga


def list_jobs(conn: sqlite3.Connection, limit: int = 100) -> list[dict]:
    return [
        clean_row(row)
        for row in conn.execute(
            """
            SELECT
                j.*,
                m.title AS manga_title,
                c.chapter_key,
                c.label AS chapter_label
            FROM jobs j
            LEFT JOIN manga m ON m.id = j.manga_id
            LEFT JOIN chapters c ON c.id = j.chapter_id
            ORDER BY j.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    ]


def list_failed_download_jobs(conn: sqlite3.Connection) -> list[dict]:
    return [
        clean_row(row)
        for row in conn.execute(
            """
            SELECT
                j.*,
                m.title AS manga_title,
                c.chapter_key,
                c.label AS chapter_label
            FROM jobs j
            LEFT JOIN manga m ON m.id = j.manga_id
            LEFT JOIN chapters c ON c.id = j.chapter_id
            WHERE j.type = 'download' AND j.status = 'failed'
            ORDER BY COALESCE(j.finished_at, j.started_at, j.created_at) DESC, j.id DESC
            """
        ).fetchall()
    ]


def download_progress(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT
            m.id AS manga_id,
            m.title AS manga_title,
            m.url,
            m.local_folder,
            m.local_chapter_count AS existing_downloaded_count,
            m.remote_chapter_count,
            m.missing_count,
            COALESCE(ch.downloaded_count, 0) AS newly_downloaded_count,
            SUM(CASE WHEN j.status IN ('queued', 'running', 'done', 'failed', 'paused', 'auto_paused') THEN 1 ELSE 0 END) AS job_total,
            SUM(CASE WHEN j.status = 'done' THEN 1 ELSE 0 END) AS job_done,
            SUM(CASE WHEN j.status = 'running' THEN 1 ELSE 0 END) AS running,
            SUM(CASE WHEN j.status = 'queued' THEN 1 ELSE 0 END) AS queued,
            SUM(CASE WHEN j.status IN ('paused', 'auto_paused') THEN 1 ELSE 0 END) AS paused,
            SUM(CASE WHEN j.status = 'failed' THEN 1 ELSE 0 END) AS failed,
            MAX(j.finished_at) AS last_finished_at,
            MAX(j.started_at) AS last_started_at
        FROM manga m
        LEFT JOIN jobs j ON j.manga_id = m.id AND j.type = 'download'
        LEFT JOIN (
            SELECT manga_id, COUNT(*) AS downloaded_count
            FROM chapters
            WHERE is_downloaded = 1
            GROUP BY manga_id
        ) ch ON ch.manga_id = m.id
        GROUP BY m.id, m.title
        HAVING job_total > 0 OR m.local_chapter_count > 0 OR COALESCE(ch.downloaded_count, 0) > 0 OR m.missing_count > 0
        ORDER BY
            CASE WHEN running > 0 THEN 0 WHEN queued > 0 THEN 1 ELSE 2 END,
            m.missing_count DESC,
            m.title COLLATE NOCASE
        LIMIT 250
        """
    ).fetchall()
    progress = []
    for row in rows:
        item = clean_row(row)
        existing = int(item["existing_downloaded_count"] or 0)
        newly = int(item["newly_downloaded_count"] or 0)
        job_total = int(item["job_total"] or 0)
        remote = int(item["remote_chapter_count"] or 0)
        total = remote or max(existing + newly + job_total, 0)
        available = min(total, existing + newly) if total else existing + newly
        item["total"] = total
        item["done"] = available
        item["available_count"] = available
        item["job_total"] = job_total
        item["job_done"] = int(item["job_done"] or 0)
        item["percent"] = round((available / total) * 100, 1) if total else 0
        progress.append(item)
    return progress


def summary(conn: sqlite3.Connection) -> dict:
    manga_count = conn.execute("SELECT COUNT(*) AS count FROM manga").fetchone()["count"]
    local_books = conn.execute("SELECT COUNT(*) AS count FROM local_inventory").fetchone()["count"]
    local_chapters = conn.execute("SELECT COALESCE(SUM(chapter_count), 0) AS count FROM local_inventory").fetchone()["count"]
    queued = conn.execute("SELECT COUNT(*) AS count FROM jobs WHERE status = 'queued'").fetchone()["count"]
    running = conn.execute("SELECT COUNT(*) AS count FROM jobs WHERE status = 'running'").fetchone()["count"]
    failed = conn.execute("SELECT COUNT(*) AS count FROM jobs WHERE status = 'failed'").fetchone()["count"]
    paused = conn.execute("SELECT COUNT(*) AS count FROM jobs WHERE status = 'paused'").fetchone()["count"]
    missing = conn.execute("SELECT COALESCE(SUM(missing_count), 0) AS count FROM manga").fetchone()["count"]
    last_scan = conn.execute("SELECT MAX(last_scanned_at) AS value FROM manga").fetchone()["value"]
    return {
        "knownManga": manga_count,
        "localBooks": local_books,
        "localChapters": local_chapters,
        "queuedJobs": queued,
        "runningJobs": running,
        "failedJobs": failed,
        "pausedJobs": paused,
        "missingChapters": missing,
        "lastScanAt": last_scan,
    }
