import sqlite3
import unittest

from backend.app import repository
from backend.app.database import init_db
from backend.app.komga import KomgaClient, KomgaSettings, latest_read_book, komga_book_url


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
        self.assertEqual(result["komga_url"], "https://komga.test/book/book-10")

    def test_komga_book_url_uses_public_book_route(self):
        self.assertEqual(
            komga_book_url("https://komga.emperordanivn.com", "0NR552YX3MQME"),
            "https://komga.emperordanivn.com/book/0NR552YX3MQME",
        )

    def test_komga_client_marks_series_unread(self):
        client = KomgaClient(KomgaSettings("https://komga.test", "", "", "/books"))
        session = FakeKomgaSession()
        client.session = session

        client.mark_series_unread("series-1")

        self.assertEqual(session.calls, [("DELETE", "https://komga.test/api/v1/series/series-1/read-progress", None)])

    def test_komga_client_marks_books_read_through_chapter_including_intro_and_zero(self):
        client = KomgaClient(KomgaSettings("https://komga.test", "", "", "/books"))
        session = FakeKomgaSession()
        client.session = session

        marked = client.mark_books_read_through_chapter(
            [
                {"id": "intro", "name": "Intro", "metadata": {"title": "Intro"}},
                {"id": "zero", "name": "Chapter 0", "metadata": {"numberSort": 0}},
                {"id": "one", "name": "Chapter 1", "metadata": {"numberSort": 1}},
                {"id": "two", "name": "Chapter 2", "metadata": {"numberSort": 2}},
            ],
            1,
        )

        self.assertEqual(marked, 3)
        self.assertEqual(
            session.calls,
            [
                ("PATCH", "https://komga.test/api/v1/books/intro/read-progress", {"completed": True, "page": 0}),
                ("PATCH", "https://komga.test/api/v1/books/zero/read-progress", {"completed": True, "page": 0}),
                ("PATCH", "https://komga.test/api/v1/books/one/read-progress", {"completed": True, "page": 0}),
            ],
        )

    def test_komga_client_marks_low_progress_series_unread_across_libraries(self):
        client = KomgaClient(KomgaSettings("https://komga.test", "", "", "/books"))
        session = FakeKomgaSession()
        session.libraries = [{"id": "library-1"}, {"id": "library-2"}]
        session.series_by_library = {
            "library-1": [{"id": "low"}, {"id": "enough"}],
            "library-2": [{"id": "empty"}],
        }
        session.books_by_series = {
            "low": [
                *[
                    {"id": f"low-read-{index}", "readStatus": "READ", "readProgress": {"completed": True}}
                    for index in range(12)
                ],
                *[
                    {"id": f"low-progress-{index}", "readStatus": "IN_PROGRESS", "readProgress": {"page": 3}}
                    for index in range(8)
                ],
                {"id": "low-unread", "readStatus": "UNREAD", "readProgress": None},
            ],
            "enough": [
                {"id": f"enough-read-{index}", "readStatus": "READ", "readProgress": {"completed": True}}
                for index in range(30)
            ],
            "empty": [
                {"id": "empty-unread", "readStatus": "UNREAD", "readProgress": None},
            ],
        }
        client.session = session

        result = client.mark_low_progress_series_unread(30)

        self.assertEqual(
            result,
            {
                "libraries": 2,
                "seriesChecked": 3,
                "seriesMarkedUnread": 2,
                "errors": [],
            },
        )
        self.assertEqual(
            sorted(call[1] for call in session.calls if call[0] == "DELETE"),
            [
                "https://komga.test/api/v1/series/empty/read-progress",
                "https://komga.test/api/v1/series/low/read-progress",
            ],
        )


class FakeKomgaResponse:
    data: dict | list = {}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict | list:
        return self.data


class FakeKomgaSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []
        self.libraries: list[dict] = []
        self.series_by_library: dict[str, list[dict]] = {}
        self.books_by_series: dict[str, list[dict]] = {}

    def get(self, url: str, params: dict | None = None, timeout: int = 30) -> FakeKomgaResponse:
        self.calls.append(("GET", url, params))
        response = FakeKomgaResponse()
        response.data = self.libraries
        return response

    def post(self, url: str, json: dict | None = None, params: dict | None = None, timeout: int = 30) -> FakeKomgaResponse:
        self.calls.append(("POST", url, json))
        response = FakeKomgaResponse()
        if url.endswith("/api/v1/series/list?unpaged=true"):
            library_id = str(((json or {}).get("condition") or {}).get("libraryId", {}).get("value") or "")
            response.data = {"content": self.series_by_library.get(library_id, [])}
        elif url.endswith("/api/v1/books/list"):
            series_id = str(((json or {}).get("condition") or {}).get("seriesId", {}).get("value") or "")
            response.data = {"content": self.books_by_series.get(series_id, [])}
        else:
            response.data = {}
        return response

    def delete(self, url: str, timeout: int) -> FakeKomgaResponse:
        self.calls.append(("DELETE", url, None))
        return FakeKomgaResponse()

    def patch(self, url: str, json: dict, timeout: int) -> FakeKomgaResponse:
        self.calls.append(("PATCH", url, json))
        return FakeKomgaResponse()


if __name__ == "__main__":
    unittest.main()
