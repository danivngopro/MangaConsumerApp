import unittest

from backend.app.asura import AsuraClient


class StaticAsuraClient(AsuraClient):
    def __init__(self, html: str) -> None:
        super().__init__("https://asurascans.com", 0)
        self.html = html

    def _get(self, path_or_url: str) -> str:
        return self.html


class AsuraMetadataTests(unittest.TestCase):
    def test_fetch_series_extracts_detail_page_metadata_genres_and_creators(self):
        html = """
        <html>
          <head>
            <link rel="canonical" href="https://asurascans.com/comics/i-am-the-fated-villain" />
            <meta property="og:title" content="I Am the Fated Villain | Asura Scans" />
            <meta property="og:image" content="https://cdn.asurascans.com/asura-images/covers/i-am-the-fated-villain.webp" />
            <meta property="og:description" content="A villain story." />
          </head>
          <body>
            <span>Status</span><span>ongoing</span>
            <span>Type</span><span>manhua</span>
            <span>Author</span><a href="/browse?author=%E5%A4%A9%E5%91%BD%E5%8F%8D%E6%B4%BE">Author Name</a>
            <span>Artist</span><a href="/browse?artist=Kuaikan">Kuaikan</a>
            <a href="/browse?genres=action"> Action </a>
            <a href="/browse?genres=fantasy"> Fantasy </a>
            <a href="/browse?genres=villain"> Villain </a>
            <a href="/comics/i-am-the-fated-villain/chapter/1">Chapter 1</a>
          </body>
        </html>
        """

        series, _chapters = StaticAsuraClient(html).fetch_series("https://asurascans.com/comics/i-am-the-fated-villain")

        self.assertEqual(series.type, "manhua")
        self.assertEqual(series.author, "Author Name")
        self.assertEqual(series.artist, "Kuaikan")
        self.assertEqual(
            series.genres,
            [
                {"name": "Action", "slug": "action"},
                {"name": "Fantasy", "slug": "fantasy"},
                {"name": "Villain", "slug": "villain"},
            ],
        )

