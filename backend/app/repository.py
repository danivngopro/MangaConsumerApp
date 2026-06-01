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


def get_inventory_map(conn: sqlite3.Connection) -> dict[str, dict]:
    rows = conn.execute("SELECT * FROM local_inventory").fetchall()
    result: dict[str, dict] = {}
    for row in rows:
        item = dict(row)
        item["chapters"] = set(json.loads(item.pop("chapters_json") or "[]"))
        result[item["normalized_title"]] = item
    return result


def upsert_manga(conn: sqlite3.Connection, manga: dict) -> int:
    now = utc_now()
    title = fix_mojibake(manga["title"])
    normalized = normalize_title(title)
    conn.execute(
        """
        INSERT INTO manga(
            slug, title, normalized_title, url, cover_url, status,
            remote_chapter_count, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(slug) DO UPDATE SET
            title = excluded.title,
            normalized_title = excluded.normalized_title,
            url = excluded.url,
            cover_url = excluded.cover_url,
            status = excluded.status,
            remote_chapter_count = excluded.remote_chapter_count,
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


def upsert_chapters(conn: sqlite3.Connection, manga_id: int, chapters: Iterable[dict]) -> None:
    now = utc_now()
    for chapter in chapters:
        key = chapter_key(chapter["number"])
        if not key:
            continue
        conn.execute(
            """
            INSERT INTO chapters(manga_id, chapter_key, label, url, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(manga_id, chapter_key) DO UPDATE SET
                label = excluded.label,
                url = excluded.url,
                updated_at = excluded.updated_at
            """,
            (manga_id, key, chapter.get("label") or f"Chapter {key}", chapter["url"], now),
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


def list_manga(conn: sqlite3.Connection) -> list[dict]:
    return [
        clean_row(row)
        for row in conn.execute(
            """
            SELECT * FROM manga
            ORDER BY missing_count DESC, title COLLATE NOCASE
            """
        ).fetchall()
    ]


def get_manga_detail(conn: sqlite3.Connection, manga_id: int) -> dict | None:
    manga_row = conn.execute("SELECT * FROM manga WHERE id = ?", (manga_id,)).fetchone()
    manga = clean_row(manga_row) if manga_row else None
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
