import sqlite3
import unittest

from backend.app import repository
from backend.app.database import init_db
from backend.app.komga import latest_read_book


class BrowseLibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_list_browse_books_filters_local_library_by_chapters_genre_and_name(self):
        murim_id = repository.upsert_manga(
            self.conn,
            {
                "slug": "murim-login",
                "title": "Murim Login",
                "url": "https://asurascans.com/comics/murim-login",
                "cover_url": "https://cdn.test/murim.jpg",
                "status": "ongoing",
                "remote_chapter_count": 200,
                "type": "manhwa",
                "author": "Zero Big",
                "artist": "Jang Cheol Byeok",
                "genres": [{"name": "Action", "slug": "action"}, {"name": "Martial Arts", "slug": "martial-arts"}],
                "rating": 9.4,
                "description": "A martial arts portal story.",
            },
        )
        repository.update_manga_scan_counts(self.conn, murim_id, 120, 80, "/books/Murim Login")
        repository.update_manga_metadata_sync_status(self.conn, murim_id, "series-1", None)
        repository.upsert_inventory(self.conn, "Murim Login", "/books/Murim Login", ["1", "2", "3"])

        other_id = repository.upsert_manga(
            self.conn,
            {
                "slug": "space-chef",
                "title": "Space Chef",
                "url": "https://asurascans.com/comics/space-chef",
                "status": "completed",
                "remote_chapter_count": 12,
                "type": "manga",
                "genres": [{"name": "Comedy", "slug": "comedy"}],
            },
        )
        repository.update_manga_scan_counts(self.conn, other_id, 12, 0, "/books/Space Chef")

        result = repository.list_browse_books(
            self.conn,
            search="murim",
            genres=["action"],
            min_chapters=100,
            max_chapters=150,
            limit=20,
            offset=0,
            komga_url="https://komga.test",
        )

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["id"], murim_id)
        self.assertEqual(result["items"][0]["komga_series_url"], "https://komga.test/series/series-1")
        self.assertEqual(result["items"][0]["asura_description"], "A martial arts portal story.")

    def test_latest_read_book_uses_highest_read_or_in_progress_chapter(self):
        result = latest_read_book(
            [
                {
                    "id": "book-1",
                    "name": "Chapter 1",
                    "metadata": {"numberSort": 1, "title": "Chapter 1"},
                    "readStatus": "READ",
                    "readProgress": {"page": 24, "completed": True},
                },
                {
                    "id": "book-2",
                    "name": "Chapter 2",
                    "metadata": {"numberSort": 2, "title": "Chapter 2"},
                    "readStatus": "UNREAD",
                    "readProgress": None,
                },
                {
                    "id": "book-10",
                    "name": "Chapter 10",
                    "metadata": {"numberSort": 10, "title": "Chapter 10"},
                    "readStatus": "IN_PROGRESS",
                    "readProgress": {"page": 8, "completed": False},
                },
            ],
            "https://komga.test",
            "series-1",
        )

        self.assertEqual(result["book_id"], "book-10")
        self.assertEqual(result["chapter_key"], "10")
        self.assertEqual(result["label"], "Chapter 10")
        self.assertEqual(result["page"], 8)
        self.assertEqual(result["komga_url"], "https://komga.test/series/series-1/book/book-10")


if __name__ == "__main__":
    unittest.main()
