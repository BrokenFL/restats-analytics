import unittest

import pandas as pd

import data_analysis_functions as daf
from api.main import _is_active_as_of_mask, _is_active_now_mask
from data_cleaning import _mls_canonical_rank


def listing(
    listing_number,
    *,
    parcel_id="parcel-1",
    short_address="1 Main Street",
    city="Wellington",
    listing_date="2026-04-01",
    status="A",
    effective_active_end_date=None,
):
    return {
        "listing_number": listing_number,
        "parcel_id": parcel_id,
        "short_address": short_address,
        "city": city,
        "listing_date": listing_date,
        "status": status,
        "effective_active_end_date": effective_active_end_date,
        "cabana_flag": 0,
    }


class InventoryEligibilityTests(unittest.TestCase):
    def test_b_and_ordinary_r_rows_are_eligible(self):
        frame = pd.DataFrame(
            [
                listing("B26017908", parcel_id="castellina-3704", short_address="3704 Siena Circle"),
                listing("R11104016", parcel_id="castellina-10274", short_address="10274 Prato Street"),
            ]
        )

        self.assertEqual(daf.is_active_now(frame, as_of_date="2026-07-27").tolist(), [True, True])
        self.assertEqual(_is_active_now_mask(frame, as_of_date=pd.Timestamp("2026-07-27")).tolist(), [True, True])

    def test_rx_without_exact_newer_replacement_remains_eligible(self):
        frame = pd.DataFrame([listing("RX-11100001")])

        self.assertTrue(bool(daf.is_active_now(frame, as_of_date="2026-07-27").iloc[0]))

    def test_rx_is_replaced_only_by_exact_newer_b_or_r_row(self):
        frame = pd.DataFrame(
            [
                listing("RX-11100001", listing_date="2025-04-01"),
                listing("B26050001", listing_date="2026-06-01"),
                listing("RX-11100002", parcel_id="parcel-2", short_address="2 Main Street", listing_date="2025-04-01"),
                listing("B26050002", parcel_id="parcel-3", short_address="3 Main Street", listing_date="2026-06-01"),
                listing("RX-11100003", parcel_id="parcel-4", listing_date="2025-04-01", short_address="4 Main Street"),
                listing("R11170003", parcel_id="parcel-5", listing_date="2026-06-01", short_address="4 Main Street", city="Boca Raton"),
            ]
        )

        mask = daf.is_active_now(frame, as_of_date="2026-07-27")
        self.assertEqual(mask.tolist(), [False, True, True, True, True, True])

    def test_shared_condo_parcel_does_not_cross_replace_units(self):
        frame = pd.DataFrame(
            [
                listing("RX-11100001", parcel_id="shared-building", short_address="100 Ocean Drive Unit 1", listing_date="2025-04-01"),
                listing("B26050001", parcel_id="shared-building", short_address="100 Ocean Drive Unit 2", listing_date="2026-06-01"),
            ]
        )

        self.assertEqual(daf.is_active_now(frame, as_of_date="2026-07-27").tolist(), [True, True])

    def test_newer_b_replaces_old_r_and_older_b_relist(self):
        frame = pd.DataFrame(
            [
                listing("R11170001", listing_date="2026-01-01"),
                listing("B26050001", listing_date="2026-04-01"),
                listing("B26050002", listing_date="2026-07-01"),
            ]
        )

        self.assertEqual(daf.is_active_now(frame, as_of_date="2026-07-27").tolist(), [False, False, True])

    def test_historical_snapshot_does_not_apply_a_future_replacement(self):
        frame = pd.DataFrame(
            [
                listing("RX-11100001", listing_date="2025-04-01"),
                listing("B26050001", listing_date="2026-06-01"),
            ]
        )
        frame["listing_date"] = pd.to_datetime(frame["listing_date"])

        before_replacement = daf.is_active_as_of(frame, "2026-05-31")
        after_replacement = daf.is_active_as_of(frame, "2026-06-30")
        self.assertEqual(before_replacement.tolist(), [True, False])
        self.assertEqual(after_replacement.tolist(), [False, True])
        self.assertEqual(_is_active_as_of_mask(frame, pd.Timestamp("2026-05-31")).tolist(), [True, False])

    def test_castellina_b_listings_remain_eligible_without_counterparts(self):
        frame = pd.DataFrame(
            [
                listing("B26017908", parcel_id="castellina-3704", short_address="3704 Siena Circle"),
                listing("B26037464", parcel_id="castellina-4023", short_address="4023 Siena Circle"),
                listing("B26034889", parcel_id="castellina-4452", short_address="4452 Siena Circle"),
                listing("B26021340", parcel_id="castellina-4591", short_address="4591 Siena Circle"),
            ]
        )

        self.assertEqual(daf.is_active_now(frame, as_of_date="2026-07-27").tolist(), [True, True, True, True])

    def test_b_is_current_rank_with_r_and_outranks_rx(self):
        self.assertEqual(_mls_canonical_rank("B26017908"), 0)
        self.assertEqual(_mls_canonical_rank("R11170001"), 0)
        self.assertEqual(_mls_canonical_rank("RX-11100001"), 1)


if __name__ == "__main__":
    unittest.main()
