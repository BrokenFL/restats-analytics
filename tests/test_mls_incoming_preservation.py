import sqlite3
import unittest

import pandas as pd

from data_cleaning import backfill_incoming_from_existing_mls


class MlsIncomingPreservationTests(unittest.TestCase):
    def test_float_fields_do_not_break_preservation(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.execute(
            """
            CREATE TABLE listing_details (
                listing_number TEXT,
                parcel_id TEXT,
                short_address TEXT,
                status TEXT,
                listing_date TEXT,
                sold_date TEXT,
                list_price REAL,
                remarks TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO listing_details VALUES
            ('RX-100', '12-3456-7890', '100 Ocean Ave', 'Active', '2026-08-01', NULL, 1200000.0, 'Existing detail')
            """
        )
        incoming = pd.DataFrame(
            [
                {
                    "listing_number": "R100",
                    "parcel_id": "12-3456-7890",
                    "short_address": "100 Ocean Ave",
                    "status": "Active",
                    "listing_date": "2026-08-01",
                    "sold_date": None,
                    "list_price": 1100000.0,
                    "remarks": None,
                }
            ]
        )

        result, rows_filled, fields_filled = backfill_incoming_from_existing_mls(conn, incoming)

        self.assertEqual(rows_filled, 1)
        self.assertGreaterEqual(fields_filled, 1)
        self.assertEqual(result.loc[0, "remarks"], "Existing detail")

    def test_invalid_float_parcel_values_are_ignored(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.execute("CREATE TABLE listing_details (listing_number TEXT, parcel_id TEXT)")
        incoming = pd.DataFrame(
            [
                {"listing_number": "R-invalid", "parcel_id": float("nan")},
                {"listing_number": "R-short", "parcel_id": 1.0},
            ]
        )

        result, rows_filled, fields_filled = backfill_incoming_from_existing_mls(conn, incoming)

        self.assertEqual(len(result), 2)
        self.assertEqual(rows_filled, 0)
        self.assertEqual(fields_filled, 0)
