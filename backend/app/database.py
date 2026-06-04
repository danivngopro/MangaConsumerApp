from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS manga (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    url TEXT NOT NULL,
    cover_url TEXT,
    status TEXT,
    remote_chapter_count INTEGER NOT NULL DEFAULT 0,
    local_chapter_count INTEGER NOT NULL DEFAULT 0,
    missing_count INTEGER NOT NULL DEFAULT 0,
    local_folder TEXT,
    download_folder_override TEXT,
    download_title_override TEXT,
    asura_type TEXT,
    asura_author TEXT,
    asura_artist TEXT,
    asura_genres_json TEXT NOT NULL DEFAULT '[]',
    asura_rating REAL,
    asura_description TEXT,
    asura_last_chapter_at TEXT,
    komga_series_id TEXT,
    metadata_synced_at TEXT,
    metadata_last_error TEXT,
    komga_library_id TEXT,
    komga_imported_at TEXT,
    komga_scanned_at TEXT,
    komga_last_error TEXT,
    last_scanned_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chapters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manga_id INTEGER NOT NULL REFERENCES manga(id) ON DELETE CASCADE,
    chapter_key TEXT NOT NULL,
    label TEXT NOT NULL,
    url TEXT NOT NULL,
    is_downloaded INTEGER NOT NULL DEFAULT 0,
    file_path TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(manga_id, chapter_key)
);

CREATE TABLE IF NOT EXISTS local_inventory (
    normalized_title TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    folder_path TEXT NOT NULL,
    chapter_count INTEGER NOT NULL,
    chapters_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    status TEXT NOT NULL,
    manga_id INTEGER REFERENCES manga(id) ON DELETE SET NULL,
    chapter_id INTEGER REFERENCES chapters(id) ON DELETE SET NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    priority INTEGER NOT NULL DEFAULT 0,
    payload_json TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS duplicate_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_kind TEXT NOT NULL DEFAULT 'remote_local',
    remote_manga_id INTEGER REFERENCES manga(id) ON DELETE CASCADE,
    remote_title TEXT NOT NULL,
    local_title TEXT NOT NULL,
    local_folder TEXT NOT NULL,
    remote_folder TEXT,
    local_chapter_count INTEGER NOT NULL DEFAULT 0,
    remote_chapter_count INTEGER NOT NULL DEFAULT 0,
    score REAL NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    resolved_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(candidate_kind, remote_manga_id, local_folder)
);

CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
"""


INDEXES = """
CREATE INDEX IF NOT EXISTS idx_jobs_type_status_priority ON jobs(type, status, priority DESC, id ASC);
CREATE INDEX IF NOT EXISTS idx_duplicate_candidates_status ON duplicate_candidates(status, score DESC);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    migrate_db(conn)
    conn.executescript(INDEXES)
    conn.commit()


def migrate_db(conn: sqlite3.Connection) -> None:
    manga_columns = {row["name"] for row in conn.execute("PRAGMA table_info(manga)").fetchall()}
    manga_migrations = {
        "komga_library_id": "ALTER TABLE manga ADD COLUMN komga_library_id TEXT",
        "komga_imported_at": "ALTER TABLE manga ADD COLUMN komga_imported_at TEXT",
        "komga_scanned_at": "ALTER TABLE manga ADD COLUMN komga_scanned_at TEXT",
        "komga_last_error": "ALTER TABLE manga ADD COLUMN komga_last_error TEXT",
        "download_folder_override": "ALTER TABLE manga ADD COLUMN download_folder_override TEXT",
        "download_title_override": "ALTER TABLE manga ADD COLUMN download_title_override TEXT",
        "asura_type": "ALTER TABLE manga ADD COLUMN asura_type TEXT",
        "asura_author": "ALTER TABLE manga ADD COLUMN asura_author TEXT",
        "asura_artist": "ALTER TABLE manga ADD COLUMN asura_artist TEXT",
        "asura_genres_json": "ALTER TABLE manga ADD COLUMN asura_genres_json TEXT NOT NULL DEFAULT '[]'",
        "asura_rating": "ALTER TABLE manga ADD COLUMN asura_rating REAL",
        "asura_description": "ALTER TABLE manga ADD COLUMN asura_description TEXT",
        "asura_last_chapter_at": "ALTER TABLE manga ADD COLUMN asura_last_chapter_at TEXT",
        "komga_series_id": "ALTER TABLE manga ADD COLUMN komga_series_id TEXT",
        "metadata_synced_at": "ALTER TABLE manga ADD COLUMN metadata_synced_at TEXT",
        "metadata_last_error": "ALTER TABLE manga ADD COLUMN metadata_last_error TEXT",
    }
    for column, statement in manga_migrations.items():
        if column not in manga_columns:
            conn.execute(statement)

    jobs_columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    if "priority" not in jobs_columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN priority INTEGER NOT NULL DEFAULT 0")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS duplicate_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_kind TEXT NOT NULL DEFAULT 'remote_local',
            remote_manga_id INTEGER REFERENCES manga(id) ON DELETE CASCADE,
            remote_title TEXT NOT NULL,
            local_title TEXT NOT NULL,
            local_folder TEXT NOT NULL,
            remote_folder TEXT,
            local_chapter_count INTEGER NOT NULL DEFAULT 0,
            remote_chapter_count INTEGER NOT NULL DEFAULT 0,
            score REAL NOT NULL,
            reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            resolved_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(candidate_kind, remote_manga_id, local_folder)
        )
        """
    )
    duplicate_columns = {row["name"] for row in conn.execute("PRAGMA table_info(duplicate_candidates)").fetchall()}
    if "candidate_kind" not in duplicate_columns:
        conn.execute("ALTER TABLE duplicate_candidates ADD COLUMN candidate_kind TEXT NOT NULL DEFAULT 'remote_local'")
    if "remote_folder" not in duplicate_columns:
        conn.execute("ALTER TABLE duplicate_candidates ADD COLUMN remote_folder TEXT")
    duplicate_info = {row["name"]: row for row in conn.execute("PRAGMA table_info(duplicate_candidates)").fetchall()}
    if duplicate_info.get("remote_manga_id") and int(duplicate_info["remote_manga_id"]["notnull"]):
        conn.execute("ALTER TABLE duplicate_candidates RENAME TO duplicate_candidates_old")
        conn.execute(
            """
            CREATE TABLE duplicate_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_kind TEXT NOT NULL DEFAULT 'remote_local',
                remote_manga_id INTEGER REFERENCES manga(id) ON DELETE CASCADE,
                remote_title TEXT NOT NULL,
                local_title TEXT NOT NULL,
                local_folder TEXT NOT NULL,
                local_chapter_count INTEGER NOT NULL DEFAULT 0,
                remote_chapter_count INTEGER NOT NULL DEFAULT 0,
                score REAL NOT NULL,
                reason TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                resolved_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(candidate_kind, remote_manga_id, local_folder)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO duplicate_candidates(
                id, candidate_kind, remote_manga_id, remote_title, local_title,
                local_folder, local_chapter_count, remote_chapter_count, score,
                reason, status, resolved_at, created_at, updated_at
            )
            SELECT id, COALESCE(candidate_kind, 'remote_local'), remote_manga_id,
                   remote_title, local_title, local_folder, local_chapter_count,
                   remote_chapter_count, score, reason, status, resolved_at,
                   created_at, updated_at
            FROM duplicate_candidates_old
            """
        )
        conn.execute("DROP TABLE duplicate_candidates_old")
