from datetime import date
import os
import unittest
from unittest.mock import patch

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

        self.assertTrue(output.startswith("# AZON Last updated May 13, 2026\n"))
        self.assertIn("OwnerDomain=AZON.games\nnetwork.com, id, DIRECT", output)
        self.assertNotIn("OwnerDomain=Old.example", output)
        self.assertNotIn("adcolony.com", output)
        self.assertNotIn("Verve.com", output)
        self.assertIn("verve.com, 15290, RESELLER, 0c8f5958fc2d6270", output)

    def test_month_day_year_has_no_leading_zero(self) -> None:
        self.assertEqual(updater.month_day_year(date(2026, 5, 13)), "May 13, 2026")

    def test_source_access_from_env_reads_mintegral_settings(self) -> None:
        env = {
            "MINTEGRAL_SOURCE_URL": "https://example.com/app-ads.txt",
            "MINTEGRAL_LOGIN": "user",
            "MINTEGRAL_PASSWORD": "password",
        }
        with patch.dict(os.environ, env, clear=True):
            source = updater.source_access_from_env("mintegral")

        self.assertEqual(source.name, "mintegral")
        self.assertEqual(source.url, "https://example.com/app-ads.txt")
        self.assertEqual(source.login, "user")
        self.assertEqual(source.password, "password")

    def test_source_access_from_env_rejects_unknown_source(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "Unknown source"):
            updater.source_access_from_env("unknown")

    def test_looks_like_ads_txt_accepts_ads_line(self) -> None:
        text = "# Network\nexample.com, pub-123, DIRECT, abcdef\n"
        self.assertTrue(updater.looks_like_ads_txt(text))

    def test_looks_like_ads_txt_rejects_html(self) -> None:
        text = "<!DOCTYPE html>\n<html lang=\"en\">\n"
        self.assertFalse(updater.looks_like_ads_txt(text))

    def test_extract_mintegral_ads_txt_from_html_block(self) -> None:
        html = """
        <!DOCTYPE html>
        <html>
          <body>
            <p>Please replace your PublisherID with your actual publisher id acquired from Mintegral dashboard.</p>
            <pre>
              mintegral.com, your PublisherID, DIRECT, 0aeed750c80d6423
              example.com, 123, RESELLER, abc
              aniview.com, 69d24331b4476e4a300e1584, RESELLER, 78b21b
              ignored.com, 123, RESELLER
            </pre>
          </body>
        </html>
        """

        output = updater.extract_mintegral_ads_txt(html)

        self.assertEqual(
            output,
            "\n".join(
                [
                    "mintegral.com, 47780, DIRECT, 0aeed750c80d6423",
                    "example.com, 123, RESELLER, abc",
                    "aniview.com, 69d24331b4476e4a300e1584, RESELLER, 78b21b",
                    "",
                ]
            ),
        )

    def test_extract_mintegral_ads_txt_falls_back_to_publisher_id(self) -> None:
        html = """
        <!DOCTYPE html>
        <html>
          <body>
            <div>mintegral.com, your publisherid, DIRECT, 0aeed750c80d6423</div>
            <div>aniview.com, 69d24331b4476e4a300e1584, RESELLER, 78b21b</div>
          </body>
        </html>
        """

        output = updater.extract_mintegral_ads_txt(html)

        self.assertIn("mintegral.com, 47780, DIRECT, 0aeed750c80d6423\n", output)
        self.assertTrue(output.endswith("aniview.com, 69d24331b4476e4a300e1584, RESELLER, 78b21b\n"))


if __name__ == "__main__":
    unittest.main()
