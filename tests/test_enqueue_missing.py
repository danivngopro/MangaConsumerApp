import sqlite3
import unittest

from backend.app import repository
from backend.app.database import init_db


class EnqueueMissingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def _insert_manga(self, slug: str, title: str, local_folder: str | None, missing_count: int) -> int:
        return self.conn.execute(
            """
            INSERT INTO manga(
                slug, title, normalized_title, url, remote_chapter_count,
                local_chapter_count, missing_count, local_folder, updated_at
            )
            VALUES (?, ?, ?, ?, 0, 0, ?, ?, 'now')
            """,
            (slug, title, repository.normalize_title(title), f"https://example.test/{slug}", missing_count, local_folder),
        ).lastrowid

    def _insert_chapters(self, manga_id: int, keys: list[str]) -> None:
        self.conn.executemany(
            """
            INSERT INTO chapters(manga_id, chapter_key, label, url, is_downloaded, updated_at)
            VALUES (?, ?, ?, ?, 0, 'now')
            """,
            [(manga_id, key, f"Chapter {key}", f"/chapter/{key}") for key in keys],
        )

    def test_enqueue_all_missing_uses_current_missing_state_not_every_undownloaded_catalog_chapter(self):
        stale_id = self._insert_manga("stale", "Stale Catalog", None, 0)
        active_id = self._insert_manga("active", "Active Book", "/books/Active Book", 2)
        self._insert_chapters(stale_id, ["1", "2", "3", "4", "5"])
        self._insert_chapters(active_id, ["1", "2", "3", "4", "5"])
        repository.upsert_inventory(self.conn, "Active Book", "/books/Active Book", ["1", "2", "3"])

        enqueued = repository.enqueue_all_missing(self.conn)
        jobs = self.conn.execute(
            """
            SELECT m.slug, c.chapter_key
            FROM jobs j
            JOIN manga m ON m.id = j.manga_id
            JOIN chapters c ON c.id = j.chapter_id
            ORDER BY m.slug, CAST(c.chapter_key AS REAL)
            """
        ).fetchall()

        self.assertEqual(enqueued, 2)
        self.assertEqual([(row["slug"], row["chapter_key"]) for row in jobs], [("active", "4"), ("active", "5")])


if __name__ == "__main__":
    unittest.main()
