from datetime import date
import unittest

import app_ads_updater as updater


class AppAdsUpdaterTest(unittest.TestCase):
    def test_parse_month_day_year_date(self) -> None:
        self.assertEqual(updater.parse_date_from_line("# Updated May 13, 2026"), date(2026, 5, 13))

    def test_parse_iso_date(self) -> None:
        self.assertEqual(updater.parse_date_from_line("# Updated 2026-05-13"), date(2026, 5, 13))

    def test_source_is_current_allows_tomorrow(self) -> None:
        self.assertTrue(updater.source_is_current("# Updated May 14, 2026", date(2026, 5, 13)))

    def test_source_is_current_rejects_yesterday(self) -> None:
        self.assertFalse(updater.source_is_current("# Updated May 12, 2026", date(2026, 5, 13)))

    def test_build_output_replaces_source_second_line(self) -> None:
        source = "# Updated May 13, 2026\nOwnerDomain=Old.example\nnetwork.com, id, DIRECT\n"
        output = updater.build_output(source, date(2026, 5, 13))

        self.assertTrue(output.startswith("# AZON Updated May 13, 2026 \n"))
        self.assertIn("OwnerDomain=AZON.games\nnetwork.com, id, DIRECT", output)
        self.assertNotIn("OwnerDomain=Old.example", output)

    def test_month_day_year_has_no_leading_zero(self) -> None:
        self.assertEqual(updater.month_day_year(date(2026, 5, 13)), "May 13, 2026")


if __name__ == "__main__":
    unittest.main()
