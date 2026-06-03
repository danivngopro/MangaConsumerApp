import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.app.database import init_db
from backend.app.library import scan_library


class LibraryScanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_scan_library_counts_nested_comic_files_inside_book_folders(self):
        with tempfile.TemporaryDirectory() as root:
            library_root = Path(root)
            book = library_root / "Demo Book"
            volume = book / "Volume 01"
            volume.mkdir(parents=True)
            (book / "Demo Book - Chapter 1.cbz").write_bytes(b"cbz")
            (volume / "Demo Book - Chapter 2.cbz").write_bytes(b"cbz")

            result = scan_library(self.conn, library_root)

        inventory = self.conn.execute("SELECT * FROM local_inventory").fetchone()
        self.assertEqual(result["books"], 1)
        self.assertEqual(result["chapters"], 2)
        self.assertEqual(result["foldersSeen"], 1)
        self.assertEqual(result["comicFilesSeen"], 2)
        self.assertEqual(inventory["chapter_count"], 2)


if __name__ == "__main__":
    unittest.main()
