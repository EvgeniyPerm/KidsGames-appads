from datetime import date
import os
import tempfile
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

        self.assertTrue(output.startswith("# KidsGames Last updated May 13, 2026\n"))
        self.assertIn("OwnerDomain=kidsgames.top\nnetwork.com, id, DIRECT", output)
        self.assertNotIn("OwnerDomain=Old.example", output)
        self.assertNotIn("adcolony.com", output)
        self.assertNotIn("Verve.com", output)
        self.assertIn("verve.com, 15290, RESELLER, 0c8f5958fc2d6270", output)

    def test_build_output_appends_extra_sources(self) -> None:
        source = "# Updated May 13, 2026\nOwnerDomain=Old.example\nnetwork.com, id, DIRECT\n"
        output = updater.build_output(
            source,
            date(2026, 5, 13),
            [("UNITY", "unity.com, 1579076, DIRECT, 96cabb5fbdde37a7\n")],
        )

        self.assertIn("# UNITY app-ads.txt\nunity.com, 1579076, DIRECT, 96cabb5fbdde37a7\n", output)

    def test_fetch_extra_source_texts_uses_cached_version_when_source_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = updater.Path(temp_dir)
            (cache_dir / "yandex.txt").write_text("cached.com, 1, RESELLER\n", encoding="utf-8")
            calls = []

            def fake_fetch(source_name: str) -> tuple[str, str]:
                calls.append(source_name)
                if source_name == "yandex":
                    raise RuntimeError("expired cookie")
                return source_name.upper(), "fresh.com, 2, DIRECT\n"

            with patch.object(updater, "SOURCE_CACHE_DIR", cache_dir):
                with patch.object(updater, "fetch_one_extra_source_text", side_effect=fake_fetch):
                    output = updater.fetch_extra_source_texts(["yandex", "dtexchange"])

        self.assertEqual(calls, ["yandex", "dtexchange"])
        self.assertEqual(
            output,
            [
                ("YANDEX", "cached.com, 1, RESELLER\n"),
                ("DTEXCHANGE", "fresh.com, 2, DIRECT\n"),
            ],
        )

    def test_fetch_extra_source_texts_raises_when_source_fails_without_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(updater, "SOURCE_CACHE_DIR", updater.Path(temp_dir)):
                with patch.object(updater, "fetch_one_extra_source_text", side_effect=RuntimeError("offline")):
                    with self.assertRaisesRegex(RuntimeError, "no cached previous version"):
                        updater.fetch_extra_source_texts(["yandex"])

    def test_fetch_one_extra_source_text_writes_cache(self) -> None:
        source = updater.SourceAccess(
            name="yandex",
            url="https://example.com/app-ads.txt",
            login=None,
            password=None,
            headers={},
            use_basic_auth=False,
            method="GET",
            payload=None,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = updater.Path(temp_dir)
            with patch.object(updater, "SOURCE_CACHE_DIR", cache_dir):
                with patch.object(updater, "source_access_from_env", return_value=source):
                    with patch.object(updater, "fetch_text", return_value="fresh.com, 2, DIRECT\n"):
                        label, text = updater.fetch_one_extra_source_text("yandex")

            cached_text = (cache_dir / "yandex.txt").read_text(encoding="utf-8")

        self.assertEqual(label, "YANDEX")
        self.assertEqual(text, "fresh.com, 2, DIRECT\n")
        self.assertEqual(cached_text, "fresh.com, 2, DIRECT\n")

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
        self.assertEqual(source.headers, {})
        self.assertTrue(source.use_basic_auth)

    def test_source_access_from_env_uses_default_bigo_url_and_tokens(self) -> None:
        env = {
            "BIGO_TOKEN": "token-one",
            "BIGO_TOKEN2": "token-two",
        }
        with patch.dict(os.environ, env, clear=True):
            source = updater.source_access_from_env("bigo")

        self.assertEqual(source.name, "bigo")
        self.assertEqual(source.url, "https://www.bigossp.com/union/app-ads-txt/developer/list")
        self.assertEqual(source.headers["x-auth-token"], "token-one")
        self.assertEqual(source.headers["bigo-ads-uid"], "token-two")
        self.assertEqual(source.headers["Accept"], "application/json, text/plain, */*")
        self.assertEqual(source.headers["Content-Type"], "application/json")
        self.assertEqual(source.method, "POST")
        self.assertEqual(source.payload, b"{}")

    def test_source_access_from_env_allows_bigo_header_and_payload_override(self) -> None:
        env = {
            "BIGO_TOKEN": "token-one",
            "BIGO_TOKEN2": "token-two",
            "BIGO_TOKEN_HEADER": "Authorization",
            "BIGO_TOKEN2_HEADER": "x-second-token",
            "BIGO_PAYLOAD": "{\"pageNo\":1}",
        }
        with patch.dict(os.environ, env, clear=True):
            source = updater.source_access_from_env("bigo")

        self.assertEqual(source.headers["Authorization"], "token-one")
        self.assertEqual(source.headers["x-second-token"], "token-two")
        self.assertEqual(source.payload, b'{"pageNo":1}')

    def test_source_access_from_env_uses_default_bidmachine_url_and_token(self) -> None:
        env = {
            "BIDMACHINE_TOKEN": "access-token",
        }
        with patch.dict(os.environ, env, clear=True):
            source = updater.source_access_from_env("bidmachine")

        self.assertEqual(source.name, "bidmachine")
        self.assertEqual(source.url, "https://dashboard.bidmachine.io/app-ads/file/sellerId=789")
        self.assertEqual(source.headers["X-Auth-Token"], "access-token")
        self.assertEqual(source.headers["Accept"], "text/plain, */*")
        self.assertEqual(source.method, "GET")
        self.assertIsNone(source.payload)

    def test_source_access_from_env_uses_default_yandex_url_and_token(self) -> None:
        env = {
            "YANDEX_TOKEN": "access-token",
        }
        with patch.dict(os.environ, env, clear=True):
            source = updater.source_access_from_env("yandex")

        self.assertEqual(source.name, "yandex")
        self.assertEqual(source.url, "https://partner.yandex.ru/restapi/v1/api/files/sellers/app-ads.txt")
        self.assertEqual(source.headers["Authorization"], "OAuth access-token")
        self.assertEqual(source.headers["Accept"], "application/json, text/plain, */*")
        self.assertFalse(source.use_basic_auth)
        self.assertEqual(source.method, "GET")
        self.assertIsNone(source.payload)

    def test_source_access_from_env_reads_yandex_access_token_from_url_fragment(self) -> None:
        env = {
            "YANDEX_URL": "https://oauth.yandex.ru/verification_code#access_token=fragment-token&token_type=bearer",
        }
        with patch.dict(os.environ, env, clear=True):
            source = updater.source_access_from_env("yandex")

        self.assertEqual(source.url, "https://partner.yandex.ru/restapi/v1/api/files/sellers/app-ads.txt")
        self.assertEqual(source.headers["Authorization"], "OAuth fragment-token")

    def test_source_access_from_env_reads_second_yandex_cookie(self) -> None:
        env = {
            "YANDEX_ADD_COOKIE": "Session_id=second",
        }
        with patch.dict(os.environ, env, clear=True):
            source = updater.source_access_from_env("yandex_add")

        self.assertEqual(source.name, "yandex_add")
        self.assertEqual(source.url, "https://partner.yandex.ru/restapi/v1/api/files/sellers/app-ads.txt")
        self.assertEqual(source.headers["Cookie"], "Session_id=second")
        self.assertFalse(source.use_basic_auth)

    def test_source_access_from_env_reads_yandex2_cookie(self) -> None:
        env = {
            "YANDEX2_COOKIE": "Session_id=second",
        }
        with patch.dict(os.environ, env, clear=True):
            source = updater.source_access_from_env("yandex2")

        self.assertEqual(source.name, "yandex2")
        self.assertEqual(source.url, "https://partner.yandex.ru/restapi/v1/api/files/sellers/app-ads.txt")
        self.assertEqual(source.headers["Cookie"], "Session_id=second")
        self.assertFalse(source.use_basic_auth)

    def test_source_access_from_env_uses_default_dtexchange_url(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            source = updater.source_access_from_env("dtexchange")

        self.assertEqual(source.name, "dtexchange")
        self.assertEqual(source.url, "https://www.digitalturbine.com/dt-app-ads.txt")
        self.assertTrue(source.use_basic_auth)
        self.assertEqual(source.method, "GET")
        self.assertIsNone(source.payload)

    def test_source_access_from_env_uses_default_inmobi_url_and_headers(self) -> None:
        env = {
            "INMOBI_AUTHORIZATION": "Bearer token",
            "INMOBI_COOKIE": "session=value",
        }
        with patch.dict(os.environ, env, clear=True):
            source = updater.source_access_from_env("inmobi")

        self.assertEqual(source.name, "inmobi")
        self.assertEqual(source.url, "https://publisher.inmobi.com/ads-txt/app-ads")
        self.assertEqual(source.headers["Authorization"], "Bearer token")
        self.assertEqual(source.headers["Cookie"], "session=value")
        self.assertIn("text/html", source.headers["Accept"])
        self.assertFalse(source.use_basic_auth)
        self.assertEqual(source.method, "GET")
        self.assertIsNone(source.payload)

    def test_source_access_from_env_uses_default_ironsource_url(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            source = updater.source_access_from_env("ironsource")

        self.assertEqual(source.name, "ironsource")
        self.assertEqual(
            source.url,
            "https://docs.unity.com/en-us/grow/is-ads/user-acquisition/ironsource-exchange/app-ads-txt",
        )
        self.assertTrue(source.use_basic_auth)
        self.assertEqual(source.method, "GET")
        self.assertIsNone(source.payload)

    def test_source_access_from_env_reads_unity_headers(self) -> None:
        env = {
            "UNITY_SOURCE_URL": "https://services.unity.com/api/monetize/app-ads/v1/organizations/1/developers/2/missing-app-ads",
            "UNITY_AUTHORIZATION": "Bearer token",
            "UNITY_COOKIE": "session=value",
        }
        with patch.dict(os.environ, env, clear=True):
            source = updater.source_access_from_env("unity")

        self.assertEqual(source.name, "unity")
        self.assertEqual(source.headers["Authorization"], "Bearer token")
        self.assertEqual(source.headers["Cookie"], "session=value")
        self.assertEqual(source.headers["Accept"], "application/json, text/plain, */*")
        self.assertEqual(source.headers["Content-Type"], "application/json")
        self.assertEqual(source.headers["Origin"], "https://cloud.unity.com")
        self.assertEqual(source.headers["x-client-id"], "unity-dashboard")
        self.assertFalse(source.use_basic_auth)
        self.assertEqual(source.method, "POST")
        self.assertEqual(source.payload, b'{"publisherWebUrl": "https://www.kidsgames.top/app-ads.txt"}')

    def test_source_access_from_env_reads_unity_name_token_as_basic_auth(self) -> None:
        env = {
            "UNITY_SOURCE_URL": "https://services.unity.com/api/monetize/app-ads/v1/organizations/1/developers/2/missing-app-ads",
            "UNITY_NAME": "service-account-key",
            "UNITY_TOKEN": "secret-key",
        }
        with patch.dict(os.environ, env, clear=True):
            source = updater.source_access_from_env("unity")

        self.assertEqual(source.headers["Authorization"], "Basic c2VydmljZS1hY2NvdW50LWtleTpzZWNyZXQta2V5")
        self.assertFalse(source.use_basic_auth)

    def test_source_access_from_env_reads_unity_token_as_bearer_without_name(self) -> None:
        env = {
            "UNITY_SOURCE_URL": "https://services.unity.com/api/monetize/app-ads/v1/organizations/1/developers/2/missing-app-ads",
            "UNITY_TOKEN": "bearer-token",
        }
        with patch.dict(os.environ, env, clear=True):
            source = updater.source_access_from_env("unity")

        self.assertEqual(source.headers["Authorization"], "Bearer bearer-token")

    def test_source_access_from_env_prefers_unity_authorization_over_name_token(self) -> None:
        env = {
            "UNITY_SOURCE_URL": "https://services.unity.com/api/monetize/app-ads/v1/organizations/1/developers/2/missing-app-ads",
            "UNITY_AUTHORIZATION": "Bearer dashboard-token",
            "UNITY_NAME": "service-account-key",
            "UNITY_TOKEN": "secret-key",
        }
        with patch.dict(os.environ, env, clear=True):
            source = updater.source_access_from_env("unity")

        self.assertEqual(source.headers["Authorization"], "Bearer dashboard-token")

    def test_source_access_from_env_uses_default_vungle_url(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            source = updater.source_access_from_env("vungle")

        self.assertEqual(source.name, "vungle")
        self.assertEqual(source.url, "https://pub-ctrl-api.vungle.com/api/v1/adstxt/vungle")
        self.assertEqual(source.headers["Accept"], "text/plain, */*")
        self.assertTrue(source.use_basic_auth)
        self.assertEqual(source.method, "GET")
        self.assertIsNone(source.payload)

    def test_source_access_from_env_accepts_liftoff_alias(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            source = updater.source_access_from_env("liftoff")

        self.assertEqual(source.name, "liftoff")
        self.assertEqual(source.url, "https://pub-ctrl-api.vungle.com/api/v1/adstxt/vungle")

    def test_source_access_from_env_rejects_unknown_source(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "Unknown source"):
            updater.source_access_from_env("unknown")

    def test_looks_like_ads_txt_accepts_ads_line(self) -> None:
        text = "# Network\nexample.com, pub-123, DIRECT, abcdef\n"
        self.assertTrue(updater.looks_like_ads_txt(text))

    def test_looks_like_ads_txt_rejects_html(self) -> None:
        text = "<!DOCTYPE html>\n<html lang=\"en\">\n"
        self.assertFalse(updater.looks_like_ads_txt(text))

    def test_extract_unity_source_text_accepts_plain_ads_txt(self) -> None:
        text = """
        unity.com, 1579076, DIRECT, 96cabb5fbdde37a7
        ignored
        adform.com, 3400, RESELLER, 9f5210a2f0999e32
        """

        output = updater.extract_unity_source_text(text)

        self.assertEqual(
            output,
            "\n".join(
                [
                    "unity.com, 1579076, DIRECT, 96cabb5fbdde37a7",
                    "adform.com, 3400, RESELLER, 9f5210a2f0999e32",
                    "",
                ]
            ),
        )

    def test_extract_unity_source_text_accepts_nested_json(self) -> None:
        text = """
        {
          "data": {
            "missingAppAds": [
              "unity.com, 1579076, DIRECT, 96cabb5fbdde37a7",
              {"line": "themediagrid.com, FALINO, RESELLER, 9fac4a4a87c2a44f"}
            ]
          }
        }
        """

        output = updater.extract_unity_source_text(text)

        self.assertIn("unity.com, 1579076, DIRECT, 96cabb5fbdde37a7\n", output)
        self.assertIn("themediagrid.com, FALINO, RESELLER, 9fac4a4a87c2a44f\n", output)

    def test_extract_unity_source_text_accepts_dashboard_html(self) -> None:
        text = """
        <!DOCTYPE html>
        <html>
          <body>
            <div>View the full list of values that should be included in your app-ads.txt file below:</div>
            <div>
              adagio.io, 1522, RESELLER
              adform.com, 3400, RESELLER, 9f5210a2f0999e32
              app-stock.com, 358747, RESELLER
            </div>
          </body>
        </html>
        """

        output = updater.extract_unity_source_text(text)

        self.assertIn("adagio.io, 1522, RESELLER\n", output)
        self.assertIn("adform.com, 3400, RESELLER, 9f5210a2f0999e32\n", output)
        self.assertIn("app-stock.com, 358747, RESELLER\n", output)

    def test_extract_bigo_source_text_reads_nested_json_lines(self) -> None:
        text = """
        {
          "status": 0,
          "result": {
            "lines": [
              "inmobi.com, 23d316d3d980453d8ea0dcf9caec4078, RESELLER, 83e75a7ae333ca9d",
              {"line": "mindtos.com,mt0b219ff842ee3772, RESELLER"},
              "not an ads line"
            ]
          }
        }
        """

        output = updater.extract_bigo_source_text(text)

        self.assertIn("inmobi.com, 23d316d3d980453d8ea0dcf9caec4078, RESELLER, 83e75a7ae333ca9d\n", output)
        self.assertIn("mindtos.com,mt0b219ff842ee3772, RESELLER\n", output)
        self.assertNotIn("not an ads line", output)

    def test_extract_bigo_source_text_preserves_duplicate_ads_lines(self) -> None:
        text = """
        {
          "result": [
            "pubmatic.com, 163754, RESELLER, 5d62403b186f2ace",
            "pubmatic.com, 163754, RESELLER, 5d62403b186f2ace"
          ]
        }
        """

        output = updater.extract_bigo_source_text(text)

        self.assertEqual(output.count("pubmatic.com, 163754, RESELLER, 5d62403b186f2ace\n"), 2)

    def test_extract_bidmachine_source_text_preserves_source_lines(self) -> None:
        text = """
        bidmachine.io, 789, DIRECT
        bidmachine.io, 789, DIRECT
        pubmatic.com, 163754, RESELLER, 5d62403b186f2ace
        """

        output = updater.extract_bidmachine_source_text(text)

        self.assertTrue(output.startswith("bidmachine.io, 789, DIRECT\n"))
        self.assertEqual(output.count("bidmachine.io, 789, DIRECT\n"), 2)
        self.assertIn("pubmatic.com, 163754, RESELLER, 5d62403b186f2ace\n", output)

    def test_extract_bidmachine_source_text_reports_dashboard_shell(self) -> None:
        text = "<!doctype html><html><title>BidMachine</title><div id=\"application\">Loading...</div></html>"

        with self.assertRaisesRegex(RuntimeError, "dashboard HTML shell"):
            updater.extract_bidmachine_source_text(text)

    def test_extract_yandex_source_text_preserves_source_lines_from_json(self) -> None:
        text = """
        {
          "data": {
            "items": [
              "yandex.ru, 12345, DIRECT",
              "rubiconproject.com, 16356, RESELLER, 0bfd66d529a55807",
              "rubiconproject.com, 16356, RESELLER, 0bfd66d529a55807"
            ]
          }
        }
        """

        output = updater.extract_yandex_source_text(text)

        self.assertEqual(
            output,
            "yandex.ru, 12345, DIRECT\n"
            "rubiconproject.com, 16356, RESELLER, 0bfd66d529a55807\n"
            "rubiconproject.com, 16356, RESELLER, 0bfd66d529a55807\n",
        )

    def test_extract_yandex_source_text_reads_ads_lines_from_html(self) -> None:
        text = """
        <html><body>
          <div>yandex.ru, 12345, DIRECT</div>
          <div>google.com, pub-1, RESELLER, f08c47fec0942fa0</div>
        </body></html>
        """

        output = updater.extract_yandex_source_text(text)

        self.assertEqual(
            output,
            "yandex.ru, 12345, DIRECT\n"
            "google.com, pub-1, RESELLER, f08c47fec0942fa0\n",
        )

    def test_extract_source_text_prepends_yandex2_direct_lines(self) -> None:
        source = updater.SourceAccess(
            name="yandex2",
            url="https://partner.yandex.ru/restapi/v1/api/files/sellers/app-ads.txt",
            login=None,
            password=None,
            headers={},
            use_basic_auth=False,
            method="GET",
            payload=None,
        )

        output = updater.extract_source_text(source, "yandex.ru, 12345, DIRECT\n")

        self.assertEqual(
            output,
            "yango-ads.com, 104716934, DIRECT\n"
            "yango-ads.com, 97637571, DIRECT\n"
            "yango-ads.com, 1079241, DIRECT\n"
            "yango-ads.com, 305746111, DIRECT\n"
            "yandex.ru, 12345, DIRECT\n",
        )

    def test_extract_dtexchange_source_text_replaces_publisher_id_and_skips_header(self) -> None:
        text = """
        Resellers as of June 01, 2026
        fyber.com,>>>>> INSERT PUBLISHER ID HERE <<<<<,DIRECT,1ad675c9de6b5176
        33across.com,0010b00002Xbn7QAAR,RESELLER,bbea06d9c4d2853c
        Media.net,8CU132UD6,RESELLER,818f58666cabc936
        """

        output = updater.extract_dtexchange_source_text(text)

        self.assertTrue(output.startswith("fyber.com,230573,DIRECT,1ad675c9de6b5176\n"))
        self.assertIn("33across.com,0010b00002Xbn7QAAR,RESELLER,bbea06d9c4d2853c\n", output)
        self.assertIn("Media.net,8CU132UD6,RESELLER,818f58666cabc936\n", output)
        self.assertNotIn("Resellers as of", output)
        self.assertNotIn("INSERT PUBLISHER ID", output)

    def test_extract_dtexchange_source_text_preserves_duplicate_reseller_lines(self) -> None:
        text = """
        Resellers as of June 01, 2026
        fyber.com,>>>>> INSERT PUBLISHER ID HERE <<<<<,DIRECT,1ad675c9de6b5176
        Media.net,8CU132UD6,RESELLER,818f58666cabc936
        Media.net,8CU132UD6,RESELLER,818f58666cabc936
        """

        output = updater.extract_dtexchange_source_text(text)

        self.assertEqual(output.count("Media.net,8CU132UD6,RESELLER,818f58666cabc936\n"), 2)

    def test_extract_dtexchange_source_text_preserves_unexpected_nonempty_lines(self) -> None:
        text = """
        Resellers as of June 01, 2026
        fyber.com,>>>>> INSERT PUBLISHER ID HERE <<<<<,DIRECT,1ad675c9de6b5176
        unexpected source note
        Media.net,8CU132UD6,RESELLER,818f58666cabc936
        """

        output = updater.extract_dtexchange_source_text(text)

        self.assertIn("unexpected source note\n", output)

    def test_extract_inmobi_source_text_reads_html_block_after_marker(self) -> None:
        html = """
        <!DOCTYPE html>
        <html>
          <body>
            <p>Once selected, copy the lines into your app-ads.txt of apps listed in adjacent section</p>
            <pre>
              inmobi.com, 12345, DIRECT, 83e75a7ae333ca9d
              rubiconproject.com, 26132, RESELLER, 0bfd66d529a55807
              not an ads line
            </pre>
          </body>
        </html>
        """

        output = updater.extract_inmobi_source_text(html)

        self.assertEqual(
            output,
            "\n".join(
                [
                    "inmobi.com, 12345, DIRECT, 83e75a7ae333ca9d",
                    "rubiconproject.com, 26132, RESELLER, 0bfd66d529a55807",
                    "",
                ]
            ),
        )

    def test_extract_inmobi_source_text_preserves_duplicate_ads_lines(self) -> None:
        text = """
        Once selected, copy the lines into your app-ads.txt of apps listed in adjacent section
        inmobi.com, 12345, DIRECT, 83e75a7ae333ca9d
        inmobi.com, 12345, DIRECT, 83e75a7ae333ca9d
        rubiconproject.com, 26132, RESELLER, 0bfd66d529a55807
        """

        output = updater.extract_inmobi_source_text(text)

        self.assertEqual(output.count("inmobi.com, 12345, DIRECT, 83e75a7ae333ca9d\n"), 2)

    def test_extract_inmobi_source_text_reports_login_shell(self) -> None:
        text = """<html><script>window['inmobiConf'] = {"loginUrl":"https://iam.inmobi.com/iam/v3/user/signin"}</script></html>"""

        with self.assertRaisesRegex(RuntimeError, "authenticated session"):
            updater.extract_inmobi_source_text(text)

    def test_extract_ironsource_source_text_replaces_account_and_owner_domain(self) -> None:
        html = """
        <!DOCTYPE html>
        <html>
          <body>
            <h2>ironSource authorized resellers</h2>
            <pre>
              OWNERDOMAIN=[yourdomain.com]
              ironsrc.com, [yourironSourcePublisherAccountID], Direct
              Remember to replace the OwnerDomain Line with your domain.
              blueseasx.com, 203625, RESELLER
              rubiconproject.com, 26132, RESELLER, 0bfd66d529a55807
            </pre>
          </body>
        </html>
        """

        output = updater.extract_ironsource_source_text(html)

        self.assertTrue(output.startswith("ironsrc.com, 338629, Direct\nOwnerDomain=kidsgames.top\n"))
        self.assertIn("blueseasx.com, 203625, RESELLER\n", output)
        self.assertIn("rubiconproject.com, 26132, RESELLER, 0bfd66d529a55807\n", output)
        self.assertNotIn("[yourironSourcePublisherAccountID]", output)
        self.assertNotIn("[yourdomain.com]", output)

    def test_extract_ironsource_source_text_reads_flattened_docs_block(self) -> None:
        text = (
            "intro ironSource authorized resellers OWNERDOMAIN=[yourdomain.com]"
            "ironsrc.com, [yourironSourcePublisherAccountID], Direct "
            "Remember to replace [yourironSourcePublisherAccountID] "
            "blueseasx.com, 203625, RESELLER rubiconproject.com, 26132, RESELLER, 0bfd66d529a55807"
        )

        output = updater.extract_ironsource_source_text(text)

        self.assertIn("blueseasx.com, 203625, RESELLER\n", output)
        self.assertIn("rubiconproject.com, 26132, RESELLER, 0bfd66d529a55807\n", output)

    def test_extract_ironsource_source_text_preserves_duplicate_reseller_lines(self) -> None:
        text = """
        ironSource authorized resellers
        rubiconproject.com, 24600, RESELLER, 0bfd66d529a55807
        rubiconproject.com, 24600, RESELLER, 0bfd66d529a55807
        blueseasx.com, 203625, RESELLER
        """

        output = updater.extract_ironsource_source_text(text)

        self.assertEqual(output.count("rubiconproject.com, 24600, RESELLER, 0bfd66d529a55807\n"), 2)

    def test_extract_vungle_source_text_replaces_first_line(self) -> None:
        text = """
        vungle.com,old,DIRECT,c107d686becd2d77
        google.com, pub-123, RESELLER, f08c47fec0942fa0
        # comment from source
        """

        output = updater.extract_vungle_source_text(text)

        self.assertTrue(output.startswith("vungle.com,669477b160e2ea00114a81e3,DIRECT,c107d686becd2d77\n"))
        self.assertIn("google.com, pub-123, RESELLER, f08c47fec0942fa0\n", output)
        self.assertIn("# comment from source\n", output)

    def test_extract_vungle_source_text_reads_json_value(self) -> None:
        text = """
        {
          "lastUpdated": "2026-06-03T01:21:53.65Z",
          "value": "vungle.com,[yourVunglePublisherAccountID],DIRECT,c107d686becd2d77\\ngoogle.com, pub-123, RESELLER, f08c47fec0942fa0\\n"
        }
        """

        output = updater.extract_vungle_source_text(text)

        self.assertTrue(output.startswith("vungle.com,669477b160e2ea00114a81e3,DIRECT,c107d686becd2d77\n"))
        self.assertIn("google.com, pub-123, RESELLER, f08c47fec0942fa0\n", output)

    def test_extract_vungle_source_text_rejects_html_shell(self) -> None:
        text = """
        <!doctype html><html><body>
        function gtag() {
        dataLayer.push(arguments);
        }
        </body></html>
        """

        with self.assertRaisesRegex(RuntimeError, "does not look like an app-ads.txt file"):
            updater.extract_vungle_source_text(text)

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
        self.assertIn("unknown-last.com, 123, RESELLER\n", output)
        self.assertTrue(output.endswith("ignored.com, 123, RESELLER\n"))

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
