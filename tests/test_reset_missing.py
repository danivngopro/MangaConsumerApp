import sqlite3
import unittest

from backend.app import repository
from backend.app.database import init_db


class ResetMissingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.manga_id = self.conn.execute(
            """
            INSERT INTO manga(
                slug, title, normalized_title, url, remote_chapter_count,
                local_chapter_count, missing_count, last_scanned_at, updated_at
            )
            VALUES ('demo', 'Demo Book', 'demo book', 'https://example.test/demo', 2, 1, 1, 'old-scan', 'now')
            """
        ).lastrowid
        self.chapter_id = self.conn.execute(
            """
            INSERT INTO chapters(manga_id, chapter_key, label, url, is_downloaded, file_path, updated_at)
            VALUES (?, '1', 'Chapter 1', '/1', 1, '/books/demo/1.cbz', 'now')
            """,
            (self.manga_id,),
        ).lastrowid
        self.conn.executemany(
            """
            INSERT INTO jobs(type, status, manga_id, chapter_id, created_at)
            VALUES ('download', ?, ?, ?, 'now')
            """,
            [
                ("queued", self.manga_id, self.chapter_id),
                ("failed", self.manga_id, self.chapter_id),
                ("done", self.manga_id, self.chapter_id),
                ("running", self.manga_id, self.chapter_id),
            ],
        )
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()

    def test_reset_missing_clears_stale_missing_and_download_bookkeeping(self):
        result = repository.reset_missing_chapters(self.conn)

        manga = self.conn.execute("SELECT * FROM manga WHERE id = ?", (self.manga_id,)).fetchone()
        chapter = self.conn.execute("SELECT * FROM chapters WHERE id = ?", (self.chapter_id,)).fetchone()
        statuses = [
            row["status"]
            for row in self.conn.execute("SELECT status FROM jobs ORDER BY id").fetchall()
        ]

        self.assertEqual(result["mangaReset"], 1)
        self.assertEqual(result["chaptersReset"], 1)
        self.assertEqual(result["jobsRemoved"], 3)
        self.assertEqual(manga["missing_count"], 0)
        self.assertEqual(manga["local_chapter_count"], 0)
        self.assertIsNone(manga["last_scanned_at"])
        self.assertEqual(chapter["is_downloaded"], 0)
        self.assertIsNone(chapter["file_path"])
        self.assertEqual(statuses, ["running"])


if __name__ == "__main__":
    unittest.main()
