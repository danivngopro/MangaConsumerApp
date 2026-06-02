import unittest
from unittest.mock import patch

from backend.app.reader_extractor import ReaderExtractionPool


class ReaderExtractionPoolTests(unittest.TestCase):
    def test_playwright_engine_does_not_start_selenium_browsers_until_fallback(self):
        with (
            patch("backend.app.reader_extractor.PlaywrightReaderPool.start"),
            patch("backend.app.reader_extractor.DriverPool.start") as selenium_start,
        ):
            pool = ReaderExtractionPool(browser_concurrency=2, reader_engine="playwright")
            pool.start()

        selenium_start.assert_not_called()

    def test_selenium_engine_starts_selenium_pool(self):
        with patch("backend.app.reader_extractor.DriverPool.start") as selenium_start:
            pool = ReaderExtractionPool(browser_concurrency=2, reader_engine="selenium")
            pool.start()

        selenium_start.assert_called_once()


if __name__ == "__main__":
    unittest.main()
