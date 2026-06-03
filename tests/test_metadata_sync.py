import sqlite3
import unittest

from backend.app import repository
from backend.app.asura import AsuraSeries
from backend.app.database import init_db
from backend.app.metadata_sync import build_komga_series_metadata, sync_manga_metadata_to_komga


class FakeKomgaClient:
    enabled = True

    def __init__(self) -> None:
        self.payloads: list[tuple[str, dict]] = []

    def find_series_for_book(self, local_title: str) -> dict | None:
        if local_title == "Murim Login":
            return {"id": "series-1", "name": "Murim Login"}
        return None

    def update_series_metadata(self, series_id: str, payload: dict) -> None:
        self.payloads.append((series_id, payload))


class MetadataSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_build_komga_metadata_maps_asura_fields_to_filterable_series_metadata(self):
        payload = build_komga_series_metadata(
            {
                "title": "Murim Login",
                "url": "https://asurascans.com/comics/murim-login",
                "status": "ongoing",
                "remote_chapter_count": 100,
                "asura_type": "manhwa",
                "asura_author": "Zero Big",
                "asura_artist": "Jang Cheol Byeok",
                "asura_genres": [
                    {"name": "Action"},
                    {"name": "Martial Arts"},
                ],
            },
            local_title="murim-login",
        )

        self.assertEqual(payload["genres"], ["Action", "Martial Arts"])
        self.assertEqual(payload["status"], "ONGOING")
        self.assertEqual(payload["readingDirection"], "WEBTOON")
        self.assertEqual(payload["publisher"], "Asura Scans")
        self.assertIn("Asura: Manhwa", payload["tags"])
        self.assertIn({"label": "Asura Scans", "url": "https://asurascans.com/comics/murim-login"}, payload["links"])
        self.assertIn({"label": "Local folder title", "title": "murim-login"}, payload["alternateTitles"])
        self.assertEqual(payload["totalBookCount"], 100)

    def test_upsert_manga_stores_asura_metadata(self):
        manga_id = repository.upsert_manga(
            self.conn,
            {
                "slug": "murim-login",
                "title": "Murim Login",
                "url": "https://asurascans.com/comics/murim-login",
                "cover_url": None,
                "status": "ongoing",
                "remote_chapter_count": 100,
                "type": "manhwa",
                "author": "Zero Big",
                "artist": "Jang Cheol Byeok",
                "genres": [{"name": "Action"}],
                "rating": 9.8,
                "last_chapter_at": "2026-06-01T00:00:00Z",
            },
        )

        row = repository.get_manga_detail(self.conn, manga_id)
        self.assertEqual(row["asura_type"], "manhwa")
        self.assertEqual(row["asura_author"], "Zero Big")
        self.assertEqual(row["asura_artist"], "Jang Cheol Byeok")
        self.assertEqual(row["asura_genres"], [{"name": "Action"}])
        self.assertEqual(row["asura_rating"], 9.8)

    def test_metadata_sync_requires_verified_mapping_before_updating_komga(self):
        manga_id = repository.upsert_manga(
            self.conn,
            {
                "slug": "murim-login",
                "title": "Murim Login",
                "url": "https://asurascans.com/comics/murim-login",
                "status": "ongoing",
                "remote_chapter_count": 100,
                "type": "manhwa",
                "genres": [{"name": "Action"}],
            },
        )
        repository.upsert_duplicate_candidate(
            self.conn,
            manga_id,
            "Murim Login",
            "murim-login",
            "/books/murim-login",
            50,
            100,
            1.0,
            "same normalized title",
        )

        result = sync_manga_metadata_to_komga(self.conn, FakeKomgaClient(), manga_id)

        self.assertEqual(result["synced"], False)
        self.assertEqual(result["needsReview"], True)

    def test_metadata_sync_updates_komga_after_duplicate_is_confirmed(self):
        manga_id = repository.upsert_manga(
            self.conn,
            {
                "slug": "murim-login",
                "title": "Murim Login",
                "url": "https://asurascans.com/comics/murim-login",
                "status": "completed",
                "remote_chapter_count": 100,
                "type": "manhwa",
                "genres": [{"name": "Action"}],
            },
        )
        candidate = repository.upsert_duplicate_candidate(
            self.conn,
            manga_id,
            "Murim Login",
            "Murim Login",
            "/books/Murim Login",
            100,
            100,
            1.0,
            "same normalized title",
        )
        repository.resolve_duplicate_candidate(self.conn, int(candidate["id"]), "confirmed_exists")
        client = FakeKomgaClient()

        result = sync_manga_metadata_to_komga(self.conn, client, manga_id)

        self.assertEqual(result["synced"], True)
        self.assertEqual(client.payloads[0][0], "series-1")
        self.assertEqual(client.payloads[0][1]["status"], "ENDED")


if __name__ == "__main__":
    unittest.main()
