import os
import unittest
from unittest.mock import patch

from backend.app.config import load_settings


class ConfigTests(unittest.TestCase):
    def test_download_defaults_are_balanced(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = load_settings()

        self.assertEqual(settings.download_concurrency, 3)
        self.assertEqual(settings.browser_concurrency, 2)
        self.assertEqual(settings.image_download_workers, 4)
        self.assertEqual(settings.reader_engine, "playwright")

    def test_runtime_concurrency_settings_are_bounded(self):
        with patch.dict(
            os.environ,
            {
                "DOWNLOAD_CONCURRENCY": "99",
                "BROWSER_CONCURRENCY": "0",
                "IMAGE_DOWNLOAD_WORKERS": "not-a-number",
                "READER_ENGINE": "unknown",
            },
            clear=True,
        ):
            settings = load_settings()

        self.assertEqual(settings.download_concurrency, 6)
        self.assertEqual(settings.browser_concurrency, 1)
        self.assertEqual(settings.image_download_workers, 4)
        self.assertEqual(settings.reader_engine, "playwright")


if __name__ == "__main__":
    unittest.main()
