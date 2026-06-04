import sqlite3
import unittest

from backend.app import repository
from backend.app.database import init_db
from backend.app.metadata_discovery import discover_unmatched_local_metadata, unmatched_local_books


class FakeAsuraSearch:
    def search_series(self, **kwargs):
        search = kwargs["search"]
        if search == "Murim Login":
            return {
                "items": [
                    {
                        "slug": "murim-login",
                        "title": "Murim Login",
                        "url": "https://asurascans.com/comics/murim-login",
                        "cover_url": None,
                        "status": "ongoing",
                        "type": "manhwa",
                        "genres": [{"name": "Action", "slug": "action"}],
                        "chapter_count": 100,
                    }
                ]
            }
        if search == "Murim Logn":
            return {
                "items": [
                    {
                        "slug": "murim-login",
                        "title": "Murim Login",
                        "url": "https://asurascans.com/comics/murim-login",
                        "cover_url": None,
                        "status": "ongoing",
                        "type": "manhwa",
                        "genres": [{"name": "Action", "slug": "action"}],
                        "chapter_count": 100,
                    }
                ]
            }
        return {"items": []}


class MetadataDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_discover_auto_links_exact_unmatched_local_book(self):
        repository.upsert_inventory(self.conn, "Murim Login", "/books/Murim Login", ["1", "2"])

        result = discover_unmatched_local_metadata(self.conn, FakeAsuraSearch())

        self.assertEqual(result["autoLinked"], 1)
        self.assertEqual(result["reviewNeeded"], 0)
        self.assertEqual(unmatched_local_books(self.conn), [])
        candidates = repository.metadata_sync_candidates(self.conn)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["local_folder"], "/books/Murim Login")
        self.assertEqual(candidates[0]["asura_genres"], [{"name": "Action", "slug": "action"}])

    def test_discover_sends_fuzzy_unmatched_local_book_to_duplicate_review(self):
        repository.upsert_inventory(self.conn, "Murim Logn", "/books/Murim Logn", ["1", "2"])

        result = discover_unmatched_local_metadata(self.conn, FakeAsuraSearch())

        self.assertEqual(result["autoLinked"], 0)
        self.assertEqual(result["reviewNeeded"], 1)
        candidates = repository.list_duplicate_candidates(self.conn)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["status"], "pending")
        self.assertEqual(candidates[0]["remote_title"], "Murim Login")
        self.assertEqual(candidates[0]["local_title"], "Murim Logn")


if __name__ == "__main__":
    unittest.main()
