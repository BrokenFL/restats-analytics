import unittest

from city_utils import canonical_city_name


class CanonicalCityNameTests(unittest.TestCase):
    def test_pandas_missing_sentinels_are_missing(self):
        for value in ("<Na>", "<NA>", "nan", "N/A", "null", None, ""):
            with self.subTest(value=value):
                self.assertIsNone(canonical_city_name(value))

    def test_known_city_is_canonicalized(self):
        self.assertEqual(canonical_city_name("south palm beach 33480"), "South Palm Beach")


if __name__ == "__main__":
    unittest.main()
