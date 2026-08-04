import unittest
from datetime import datetime, timedelta

from PalmBeachProrpertyScraper import pbc_overlap_start_date


class PbcOverlapTests(unittest.TestCase):
    def test_overlap_moves_start_before_watermark(self):
        latest = datetime(2026, 8, 3)
        self.assertEqual(pbc_overlap_start_date(latest, 90), latest - timedelta(days=90))

    def test_negative_overlap_is_rejected(self):
        with self.assertRaises(ValueError):
            pbc_overlap_start_date(datetime(2026, 8, 3), -1)

    def test_missing_watermark_returns_none(self):
        self.assertIsNone(pbc_overlap_start_date(None, 90))


if __name__ == "__main__":
    unittest.main()
