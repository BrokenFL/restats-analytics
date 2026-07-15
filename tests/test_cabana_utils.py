import unittest

import pandas as pd

from cabana_utils import likely_cabana_mask


class CabanaClassificationTests(unittest.TestCase):
    def test_marketing_remarks_do_not_exclude_residence(self):
        frame = pd.DataFrame(
            [
                {
                    "short_address": "100 Ocean Drive 4A",
                    "unit_number": "4A",
                    "legal_desc": "CONDOMINIUM UNIT 4A",
                    "public_remarks": "Assigned parking, storage and pool cabanas included.",
                    "total_bedrooms": 2,
                    "sqft_living": 1200,
                    "sold_price": 750000,
                    "list_price": 775000,
                }
            ]
        )
        self.assertFalse(bool(likely_cabana_mask(frame).iloc[0]))

    def test_explicit_cabana_unit_is_excluded(self):
        frame = pd.DataFrame(
            [
                {
                    "short_address": "100 Ocean Drive Cabana C12",
                    "unit_number": "C12",
                    "legal_desc": "CABANA UNIT C12",
                    "public_remarks": "",
                    "total_bedrooms": 0,
                    "sqft_living": 120,
                    "sold_price": 90000,
                    "list_price": 90000,
                }
            ]
        )
        self.assertTrue(bool(likely_cabana_mask(frame).iloc[0]))

    def test_zero_prefixed_residential_unit_is_not_excluded(self):
        frame = pd.DataFrame(
            [
                {
                    "short_address": "770 E Camino Real 0020",
                    "unit_number": "0020",
                    "legal_desc": "CONDOMINIUM UNIT 20",
                    "public_remarks": "Two bedroom residence with parking.",
                    "total_bedrooms": 2,
                    "sqft_living": 998,
                    "sold_price": 775000,
                    "list_price": 800000,
                }
            ]
        )
        self.assertFalse(bool(likely_cabana_mask(frame).iloc[0]))

    def test_c_prefixed_residential_unit_is_not_excluded_without_accessory_facts(self):
        frame = pd.DataFrame(
            [
                {
                    "short_address": "2871 N Ocean Boulevard C103",
                    "unit_number": "C103",
                    "legal_desc": "CONDOMINIUM UNIT C103",
                    "public_remarks": "Two bedroom residence.",
                    "total_bedrooms": 2,
                    "sqft_living": 1186,
                    "sold_price": 325000,
                    "list_price": 350000,
                }
            ]
        )
        self.assertFalse(bool(likely_cabana_mask(frame).iloc[0]))


if __name__ == "__main__":
    unittest.main()
