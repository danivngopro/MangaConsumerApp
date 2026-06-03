import sqlite3
import unittest
from datetime import datetime, timezone
from pathlib import Path

from backend.app.database import init_db
from backend.app.scheduler import ScanScheduler


class ScanSchedulerCadenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.scheduler = ScanScheduler(self.conn, client=None, library_root=Path("."))

    def tearDown(self) -> None:
        self.conn.close()

    def test_auto_scan_waits_until_two_am_when_no_previous_scan_exists(self):
        before_two = datetime(2026, 6, 3, 1, 59, tzinfo=timezone.utc)
        at_two = datetime(2026, 6, 3, 2, 0, tzinfo=timezone.utc)

        self.assertFalse(self.scheduler._is_due(1, now=before_two))
        self.assertTrue(self.scheduler._is_due(1, now=at_two))

    def test_auto_scan_runs_once_per_interval_at_two_am_or_later(self):
        self.conn.execute(
            "INSERT INTO settings(key, value) VALUES ('last_full_scan_at', ?)",
            ("2026-06-02T02:15:00+00:00",),
        )
        self.conn.commit()

        too_early = datetime(2026, 6, 3, 1, 59, tzinfo=timezone.utc)
        due = datetime(2026, 6, 3, 2, 0, tzinfo=timezone.utc)

        self.assertFalse(self.scheduler._is_due(1, now=too_early))
        self.assertTrue(self.scheduler._is_due(1, now=due))


if __name__ == "__main__":
    unittest.main()
