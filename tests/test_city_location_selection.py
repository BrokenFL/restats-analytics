import unittest
from unittest.mock import Mock, patch

from selenium.common.exceptions import TimeoutException

from CMA import mls_quicksearch_export_from_cma as scraper


def location(category, value, *, field="city", table="list", criteria=None):
    # Shape captured from FlexMLS on October 19, including blank repeated labels.
    return {
        "category": category,
        "label": value,
        "row": object(),
        "search": {
            "tb": table,
            "f": field,
            "o": "like" if table == "list" else "within",
            "c": criteria if criteria is not None else f"={value}",
            "d": "City" if field == "city" else category,
            "display_val": value,
        },
    }


class CityLocationSelectionTests(unittest.TestCase):
    def test_selector_is_preferred_even_when_advertised_as_universal_location(self):
        city = {'type': 'SS', 'id': 'city-id', 'universal': True}
        yn = {'type': 'Y', 'id': 'view-city-id', 'universal': False}
        self.assertIs(scraper._city_selector_field([yn, city]), city)

    def test_duplicate_renderings_of_one_selector_are_not_ambiguous(self):
        city = {'type': 'SS', 'id': 'city-id', 'universal': True}
        result = scraper._city_selector_field([city, {**city, 'universal': False}])
        self.assertEqual(result['id'], 'city-id')

    def test_distinct_city_selectors_remain_ambiguous(self):
        with self.assertRaisesRegex(TimeoutException, 'Multiple selectable City fields'):
            scraper._city_selector_field([{'type': 'SS', 'id': 'first'}, {'type': 'SS', 'id': 'second'}])

    def test_select_verification_requires_only_the_requested_city(self):
        self.assertTrue(scraper._city_filter_is_exact({'enabled': True, 'selected': ['PALM BEACH']}, 'Palm Beach'))
        self.assertFalse(scraper._city_filter_is_exact({'enabled': True, 'selected': ['Palm Beach', 'West Palm Beach']}, 'Palm Beach'))

    def test_universal_location_compiled_equals_city_is_exact(self):
        query = {'tb': 'list', 'f': 'city', 'o': 'like', 'c': '=Palm Beach', 'r': 'R'}
        self.assertTrue(scraper._city_filter_is_exact({'enabled': True, 'criteria': [query]}, 'Palm Beach'))
        self.assertTrue(scraper._city_filter_is_exact({'enabled': True, 'criteria': [{**query, 'c': "'=Palm Beach'"}]}, 'Palm Beach'))

    def test_fuzzy_excluded_disabled_or_extra_location_filters_are_rejected(self):
        query = {'tb': 'list', 'f': 'city', 'o': 'like', 'c': '=Palm Beach', 'r': 'R'}
        for bad in ({**query, 'c': 'Palm Beach'}, {**query, 'r': 'X'}, {**query, 'c': '=West Palm Beach'}):
            self.assertFalse(scraper._city_filter_is_exact({'enabled': True, 'criteria': [bad]}, 'Palm Beach'))
        self.assertFalse(scraper._city_filter_is_exact({'enabled': False, 'criteria': [query]}, 'Palm Beach'))
        self.assertFalse(scraper._city_filter_is_exact({'enabled': True, 'criteria': [query, {'tb': 'overlays', 'f': 'map'}]}, 'Palm Beach'))

    def test_stable_regional_banner_is_not_a_completed_city_result(self):
        state = {'total': 0, 'results_text': ': 0', 'top_text': ': 81,133', 'query_ready': False}
        self.assertIsNone(scraper._completed_result_count(state))

    def test_counts_must_agree_after_the_results_request_finishes(self):
        state = {'total': 331, 'results_text': ': 331', 'top_text': ': 81,133', 'query_ready': True}
        self.assertIsNone(scraper._completed_result_count(state))
        state['top_text'] = ': 331'
        self.assertEqual(scraper._completed_result_count(state), 331)

    def test_loading_or_dirty_query_is_never_export_ready(self):
        state = {'total': 331, 'results_text': ': 331', 'top_text': ': 331', 'query_ready': True}
        for flag in ('dirty', 'busy', 'loading'):
            with self.subTest(flag=flag):
                self.assertIsNone(scraper._completed_result_count({**state, flag: True}))

    def test_completed_empty_results_do_not_reuse_a_positive_banner(self):
        state = {'total': 0, 'results_text': ': 0', 'top_text': ': 0', 'query_ready': True}
        self.assertEqual(scraper._completed_result_count(state), 0)

    def test_login_navigates_from_blank_tab_before_waiting_for_the_form(self):
        driver = Mock(current_url="about:blank")
        calls = []
        with (
            patch.object(scraper, "_navigate", side_effect=lambda *_: calls.append("navigate")),
            patch.object(scraper, "_capture_debug"),
            patch.object(scraper, "_wait_for_auth_form", side_effect=RuntimeError("stop after navigation")),
        ):
            with self.assertRaisesRegex(RuntimeError, "stop after navigation"):
                scraper.login(driver, Mock(), "test@example.com", "unused", "")
        self.assertEqual(calls, ["navigate"])

    def test_wellington_duplicate_top_hit_is_the_same_city_query(self):
        top = location("Top Hit", "Wellington")
        city = location("City", "Wellington")
        address = location("Street Address", "WELLINGTON", field="address")
        overlay = location("Wellington Exact", "Wellington", field="overlay-id", table="overlays")
        self.assertIs(scraper._choose_city_location([top, city, address, overlay], "Wellington"), city)

    def test_palm_beach_blank_category_uses_typed_city_metadata(self):
        gardens = location("City", "Palm Beach Gardens")
        palm = location("\u00a0", "Palm Beach")
        county = location("County Or Parish", "Palm Beach", field="county")
        address = location("Street Address", "PALM BEACH", field="address")
        overlay = location("Palm beach", "Palm Beach", field="overlay-id", table="overlays")
        self.assertIs(scraper._choose_city_location([gardens, county, overlay, address, palm], "Palm Beach"), palm)

    def test_rejects_county_address_and_overlay_even_with_same_display_value(self):
        candidates = [
            location("City", "Palm Beach", field="county"),
            location("Top Hit", "Palm Beach", field="address"),
            location("City", "Palm Beach", table="overlays"),
        ]
        self.assertIsNone(scraper._choose_city_location(candidates, "Palm Beach"))

    def test_nearby_city_names_do_not_match(self):
        candidates = [location("City", name) for name in ("West Palm Beach", "South Palm Beach", "Palm Beach Gardens")]
        self.assertIsNone(scraper._choose_city_location(candidates, "Palm Beach"))

    def test_display_label_can_have_state_suffix(self):
        candidate = location("City", "Palm Beach, FL")
        self.assertIs(scraper._choose_city_location([candidate], "Palm Beach"), candidate)

    def test_distinct_city_queries_remain_ambiguous(self):
        candidates = [
            location("Top Hit", "Wellington"),
            location("City", "Wellington", criteria="different-source-code"),
        ]
        with self.assertRaisesRegex(TimeoutException, "Multiple distinct exact City filters"):
            scraper._choose_city_location(candidates, "Wellington")

    def test_empty_lookup_does_not_match(self):
        self.assertIsNone(scraper._choose_city_location([], "Palm Beach"))

    def test_verified_location_filter_does_not_require_a_select_control(self):
        driver = Mock()
        driver.execute_script.return_value = {"ok": False, "reason": "city_select_not_found"}
        with (
            patch.object(scraper, "_set_city_via_location_search", return_value=True) as picker,
            patch.object(scraper, "_capture_debug"),
        ):
            scraper._set_city_values(driver, ["Palm Beach"], "", Mock())
        picker.assert_called_once()
        self.assertEqual(driver.execute_script.call_count, 1)

    def test_added_select_control_still_sets_and_checks_requested_value(self):
        driver = Mock()
        driver.execute_script.side_effect = [
            {"ok": False, "reason": "city_select_not_found"},
            {"ok": True, "missing": []},
        ]
        with (
            patch.object(scraper, "_set_city_via_location_search", return_value=False),
            patch.object(scraper, "_capture_debug"),
        ):
            scraper._set_city_values(driver, ["Palm Beach"], "", Mock())
        self.assertEqual(driver.execute_script.call_count, 2)


if __name__ == "__main__":
    unittest.main()
