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
                    "ignored.com, 123, RESELLER",
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

    def test_extract_mintegral_ads_txt_uses_code_fence_not_known_last_line(self) -> None:
        html = """
        Please replace your PublisherID with your actual publisher id acquired from Mintegral dashboard.
        ```java
        mintegral.com, your PublisherID, DIRECT, 0aeed750c80d6423
        aniview.com, 603f65a2e291680ef30af9c7, RESELLER, 78b21b97965ec3f8
        example.com, keep-this, RESELLER
        unknown-last.com, 123, RESELLER
        ```
        ignored.com, 123, RESELLER
        """

        output = updater.extract_mintegral_ads_txt(html)

        self.assertIn("example.com, keep-this, RESELLER\n", output)
        self.assertTrue(output.endswith("unknown-last.com, 123, RESELLER\n"))
        self.assertNotIn("ignored.com, 123, RESELLER", output)

    def test_extract_mintegral_ads_txt_preserves_block_lines_as_is(self) -> None:
        text = """
        Please replace your PublisherID with your actual publisher id acquired from Mintegral dashboard.
        ```java
        mintegral.com, your PublisherID, DIRECT, 0aeed750c80d6423
        inventorypartnerdomain=thunder-monetize.com
        vidoomy.com,7646534,RESELLER
        adform.com , 2742 , RESELLER
        aniview.com, 69d24331b4476e4a300e1584, RESELLER, 78b21b
        ```
        """

        output = updater.extract_mintegral_ads_txt(text)

        self.assertIn("inventorypartnerdomain=thunder-monetize.com\n", output)
        self.assertIn("vidoomy.com,7646534,RESELLER\n", output)
        self.assertIn("adform.com , 2742 , RESELLER\n", output)

    def test_linked_javascript_urls_resolves_relative_urls(self) -> None:
        html = """<script src="/assets/app.js"></script><script src="chunk.js"></script>"""

        self.assertEqual(
            updater.linked_javascript_urls("https://example.com/docs/page", html),
            ["https://example.com/assets/app.js", "https://example.com/docs/chunk.js"],
        )

    def test_mintegral_doc_path_from_menu_resolves_about_ads(self) -> None:
        menu = (
            'var docSet = [{"key":"sdk","data":[{"key":"m_sdk","data":['
            '{"key":"about_ads","language":[{"key":"en","path":"1744799369"}]}'
            "]}]}];"
        )

        self.assertEqual(
            updater.mintegral_doc_path_from_menu(menu, "sdk-m_sdk-about_ads", "en"),
            "1744799369",
        )


if __name__ == "__main__":
    unittest.main()
