import sqlite3
import unittest

from backend.app.database import init_db


class DatabaseMigrationTests(unittest.TestCase):
    def test_init_db_migrates_existing_jobs_table_before_creating_priority_index(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                status TEXT NOT NULL,
                manga_id INTEGER,
                chapter_id INTEGER,
                attempts INTEGER NOT NULL DEFAULT 0,
                payload_json TEXT NOT NULL DEFAULT '{}',
                error TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT
            )
            """
        )

        init_db(conn)

        columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
        indexes = {row["name"] for row in conn.execute("PRAGMA index_list(jobs)").fetchall()}
        self.assertIn("priority", columns)
        self.assertIn("idx_jobs_type_status_priority", indexes)
        conn.close()


if __name__ == "__main__":
    unittest.main()
