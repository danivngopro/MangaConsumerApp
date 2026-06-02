import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import requests

from backend.app.database import init_db
from backend.app.downloader import _download_images_parallel, download_chapter


class FakeResponse:
    def __init__(self, payload: bytes, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code
        self.headers = {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error", response=self)
        return None

    def iter_content(self, chunk_size: int):
        yield self.payload


class FakeSession:
    def __init__(self) -> None:
        self.headers = {}

    def get(self, url: str, stream: bool, timeout: int):
        return FakeResponse(url.encode("utf-8"))


class SequencedSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.headers = {}
        self.responses = responses

    def get(self, url: str, stream: bool, timeout: int):
        return self.responses.pop(0)


class DownloaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.manga_id = self.conn.execute(
            """
            INSERT INTO manga(slug, title, normalized_title, url, updated_at)
            VALUES ('demo', 'Demo Book', 'demo book', 'https://example.test/comics/demo', 'now')
            """
        ).lastrowid
        self.chapter_id = self.conn.execute(
            """
            INSERT INTO chapters(manga_id, chapter_key, label, url, updated_at)
            VALUES (?, '7', 'Chapter 7', '/chapter/7', 'now')
            """,
            (self.manga_id,),
        ).lastrowid
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()

    def test_download_chapter_extracts_urls_then_writes_cbz_in_page_order(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as tmp:
            with patch("backend.app.downloader.requests.Session", FakeSession):
                cbz_path = download_chapter(
                    self.conn,
                    Path(root),
                    Path(tmp),
                    {
                        "id": self.manga_id,
                        "title": "Demo Book",
                        "url": "https://example.test/comics/demo",
                        "local_folder": None,
                    },
                    {
                        "id": self.chapter_id,
                        "chapter_key": "7",
                        "label": "Chapter 7",
                        "url": "/chapter/7",
                    },
                    extract_image_urls=lambda url: [
                        "https://asura-images.test/page-1.jpg",
                        "https://asura-images.test/page-2.jpg",
                        "https://asura-images.test/page-3.jpg",
                    ],
                    image_download_workers=2,
                )

            with zipfile.ZipFile(cbz_path) as archive:
                self.assertEqual(archive.namelist(), ["001.jpg", "002.jpg", "003.jpg"])
                self.assertEqual(archive.read("002.jpg"), b"https://asura-images.test/page-2.jpg")

            row = self.conn.execute("SELECT is_downloaded, file_path FROM chapters WHERE id = ?", (self.chapter_id,)).fetchone()
            self.assertEqual(row["is_downloaded"], 1)
            self.assertEqual(row["file_path"], cbz_path)

    def test_download_chapter_rejects_reader_pages_with_too_few_images(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "Too few page images"):
                download_chapter(
                    self.conn,
                    Path(root),
                    Path(tmp),
                    {
                        "id": self.manga_id,
                        "title": "Demo Book",
                        "url": "https://example.test/comics/demo",
                        "local_folder": None,
                    },
                    {
                        "id": self.chapter_id,
                        "chapter_key": "7",
                        "label": "Chapter 7",
                        "url": "/chapter/7",
                    },
                    extract_image_urls=lambda url: ["https://asura-images.test/page-1.jpg"],
                    image_download_workers=2,
                )

    def test_image_download_retries_429_before_failing_chapter(self):
        session = SequencedSession([
            FakeResponse(b"rate-limited", status_code=429),
            FakeResponse(b"page-ok"),
        ])
        with tempfile.TemporaryDirectory() as tmp:
            with patch("backend.app.downloader.requests.Session", return_value=session):
                with patch("backend.app.downloader.time.sleep") as sleep:
                    paths = _download_images_parallel(
                        ["https://asura-images.test/page-1.webp"],
                        Path(tmp),
                        "https://example.test/chapter/1",
                        max_workers=1,
                    )
                    self.assertEqual(len(paths), 1)
                    self.assertEqual(paths[0].read_bytes(), b"page-ok")

        sleep.assert_called()


if __name__ == "__main__":
    unittest.main()
