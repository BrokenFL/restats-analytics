import unittest

import pandas as pd

import data_cleaning


class PenthouseFloorTests(unittest.TestCase):
    def clean(self, frame):
        with self.assertNoLogs(data_cleaning.logger, level='ERROR'):
            return data_cleaning._process_chunk(frame, {})

    def test_integer_source_floor_accepts_penthouse_building_height(self):
        result = self.clean(pd.DataFrame({
            'Unit #': ['PH1', '4A'],
            'Unit Floor #': [0, 4],
            'Total Floors/Stories': [10, 10],
        }))
        self.assertEqual(result['unit_floor'].tolist(), [10.0, 4.0])

    def test_penthouse_without_building_height_keeps_source_floor(self):
        result = self.clean(pd.DataFrame({
            'Unit #': ['PH1', 'PH2'],
            'Unit Floor #': [8, 0],
            'Total Floors/Stories': [None, 10],
        }))
        self.assertEqual(result['unit_floor'].tolist(), [8.0, 10.0])

    def test_missing_source_floor_does_not_invent_non_penthouse_floor(self):
        result = self.clean(pd.DataFrame({
            'Unit #': ['PH1', '4A'],
            'Total Floors/Stories': [10, 10],
        }))
        self.assertEqual(result.loc[0, 'unit_floor'], 10.0)
        self.assertTrue(pd.isna(result.loc[1, 'unit_floor']))

    def test_non_penthouse_export_keeps_missing_floor_column(self):
        result = self.clean(pd.DataFrame({'Unit #': ['4A'], 'Total Floors/Stories': [10]}))
        self.assertTrue(pd.isna(result.loc[0, 'unit_floor']))


if __name__ == '__main__':
    unittest.main()
