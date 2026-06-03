import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.app.database import init_db
from backend.app.queue import DownloadQueue


class FakeKomgaClient:
    enabled = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, bool | None]] = []

    def import_all_books(self, library_root: Path, scan: bool = True) -> dict:
        self.calls.append(("import_all_books", scan))
        return {"scanned": 0, "created": 2, "errors": []}

    def quick_scan_all(self) -> int:
        self.calls.append(("quick_scan_all", None))
        return 2


class KomgaBatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_batch_komga_action_imports_all_then_waits_then_scans_all(self):
        client = FakeKomgaClient()
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as tmp:
            queue = DownloadQueue(
                self.conn,
                Path(root),
                Path(tmp),
                client,
                komga_post_download_delay_seconds=0,
            )

            queue.run_post_queue_komga_batch()

        self.assertEqual(client.calls, [("import_all_books", False), ("quick_scan_all", None)])


if __name__ == "__main__":
    unittest.main()
