import sqlite3
import unittest

from backend.app.database import init_db
from backend.app import repository


class TopUpStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_empty_exhausted_top_up_batch_remains_active_and_resets_catalog_offset(self):
        repository.start_limited_scan_state(self.conn, 300)

        repository.finish_limited_scan_batch(
            self.conn,
            {
                "batchMangaIds": [],
                "nextOffset": 120,
                "exhausted": True,
                "stopped": False,
                "pendingMangaId": 0,
                "pendingChapterIds": [],
            },
        )

        self.assertEqual(repository.get_setting(self.conn, "limited_scan_active"), "1")
        self.assertEqual(repository.get_setting(self.conn, "limited_scan_batch_running"), "0")
        self.assertEqual(repository.get_setting(self.conn, "limited_scan_offset"), "0")

    def test_stopped_top_up_batch_turns_top_up_off(self):
        repository.start_limited_scan_state(self.conn, 300)

        repository.finish_limited_scan_batch(
            self.conn,
            {
                "batchMangaIds": [],
                "nextOffset": 24,
                "exhausted": False,
                "stopped": True,
                "pendingMangaId": 0,
                "pendingChapterIds": [],
            },
        )

        self.assertEqual(repository.get_setting(self.conn, "limited_scan_active"), "0")


if __name__ == "__main__":
    unittest.main()
