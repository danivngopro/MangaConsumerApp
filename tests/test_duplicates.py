import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app import repository
from backend.app.asura import AsuraChapter, AsuraSeries
from backend.app.database import init_db
from backend.app.downloader import download_chapter
from backend.app.duplicates import best_title_match
from backend.app.library import scan_library
from backend.app.scanner import scan_one_series


class FakeClient:
    def __init__(self, series: AsuraSeries, chapters: list[AsuraChapter]) -> None:
        self.series = series
        self.chapters = chapters

    def fetch_series(self, _url: str):
        return self.series, self.chapters


class FakeSession:
    def __init__(self) -> None:
        self.headers = {}

    def get(self, url: str, stream: bool, timeout: int):
        class Response:
            headers = {}

            def raise_for_status(self) -> None:
                return None

            def iter_content(self, _chunk_size: int):
                yield url.encode("utf-8")

        return Response()


class DuplicateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_title_match_detects_punctuation_and_word_differences(self):
        match = best_title_match(
            "Murim Login",
            [
                {"title": "murim-login", "folder_path": "/books/murim-login", "chapters": {"1"}},
                {"title": "Other Book", "folder_path": "/books/other", "chapters": {"1"}},
            ],
        )

        self.assertIsNotNone(match)
        self.assertEqual(match["title"], "murim-login")
        self.assertGreaterEqual(match["score"], 0.8)

    def test_scan_postpones_suspected_duplicate_until_manual_resolution(self):
        with tempfile.TemporaryDirectory() as root:
            local = Path(root) / "murim-login"
            local.mkdir()
            (local / "murim-login - Chapter 1.cbz").write_bytes(b"cbz")
            scan_library(self.conn, Path(root))
            inventory = repository.get_inventory_map(self.conn)

            result = scan_one_series(
                self.conn,
                FakeClient(
                    AsuraSeries("murim-login-remote", "Murim Login", "/series/murim", None, None, 2),
                    [
                        AsuraChapter("1", "Chapter 1", "/1"),
                        AsuraChapter("2", "Chapter 2", "/2"),
                    ],
                ),
                AsuraSeries("murim-login-remote", "Murim Login", "/series/murim", None, None, 2),
                inventory,
            )

        candidates = repository.list_duplicate_candidates(self.conn)
        queued = self.conn.execute("SELECT COUNT(*) AS count FROM jobs WHERE status = 'queued'").fetchone()["count"]

        self.assertEqual(result["duplicateStatus"], "pending")
        self.assertEqual(result["enqueued"], 0)
        self.assertEqual(queued, 0)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["local_title"], "murim-login")

    def test_reindex_detects_existing_local_duplicate_folders(self):
        with tempfile.TemporaryDirectory() as root:
            keep = Path(root) / "Murim Login"
            duplicate = Path(root) / "murim-login"
            keep.mkdir()
            duplicate.mkdir()
            (keep / "Murim Login - Chapter 1.cbz").write_bytes(b"cbz")
            (keep / "Murim Login - Chapter 2.cbz").write_bytes(b"cbz")
            (duplicate / "murim-login - Chapter 1.cbz").write_bytes(b"cbz")

            scan_library(self.conn, Path(root))

        candidates = repository.list_duplicate_candidates(self.conn)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["candidate_kind"], "local_local")
        self.assertEqual(candidates[0]["remote_title"], "Murim Login")
        self.assertEqual(candidates[0]["local_title"], "murim-login")

    def test_resolving_duplicate_as_existing_enqueues_only_new_chapters_to_local_folder(self):
        with tempfile.TemporaryDirectory() as root:
            local = Path(root) / "murim-login"
            local.mkdir()
            (local / "murim-login - Chapter 1.cbz").write_bytes(b"cbz")
            scan_library(self.conn, Path(root))
            inventory = repository.get_inventory_map(self.conn)
            scan_one_series(
                self.conn,
                FakeClient(
                    AsuraSeries("murim-login-remote", "Murim Login", "/series/murim", None, None, 2),
                    [
                        AsuraChapter("1", "Chapter 1", "/1"),
                        AsuraChapter("2", "Chapter 2", "/2"),
                    ],
                ),
                AsuraSeries("murim-login-remote", "Murim Login", "/series/murim", None, None, 2),
                inventory,
            )
            candidate_id = repository.list_duplicate_candidates(self.conn)[0]["id"]

            result = repository.resolve_duplicate_candidate(self.conn, candidate_id, "confirmed_exists")

            job = repository.claim_next_download_job(self.conn)
            manga, chapter = repository.get_download_target(self.conn, job["id"])
            self.assertEqual(result["enqueued"], 1)
            self.assertEqual(chapter["chapter_key"], "2")
            self.assertEqual(manga["download_folder"], str(local))

    def test_download_chapter_writes_to_resolved_local_folder(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as tmp:
            local = Path(root) / "murim-login"
            with patch("backend.app.downloader.requests.Session", FakeSession):
                cbz = download_chapter(
                    self.conn,
                    Path(root),
                    Path(tmp),
                    {
                        "id": 1,
                        "title": "Murim Login",
                        "download_folder": str(local),
                    },
                    {
                        "id": 1,
                        "chapter_key": "51",
                        "label": "Chapter 51",
                        "url": "https://example.test/51",
                    },
                    extract_image_urls=lambda _url: [
                        "https://asura-images.test/1.jpg",
                        "https://asura-images.test/2.jpg",
                        "https://asura-images.test/3.jpg",
                    ],
                    image_download_workers=1,
                )

        self.assertTrue(cbz.startswith(str(local)))
        self.assertIn("Murim Login - Chapter 51.cbz", cbz)


if __name__ == "__main__":
    unittest.main()
