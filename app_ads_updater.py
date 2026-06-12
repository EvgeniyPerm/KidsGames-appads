from __future__ import annotations

import argparse
import base64
import ftplib
import hashlib
import html
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


SOURCE_URL = "https://raw.githubusercontent.com/cleveradssolutions/App-ads.txt/master/app-ads.txt"
DEFAULT_TIMEZONE = "Africa/Johannesburg"
DEFAULT_FTP_REMOTE_DIR = "kidsgames.top"
LOG_PATH = Path("logs/app-ads-updater.log")
SOURCE_CACHE_DIR = Path("source-cache")
WIX_ADS_TXT_URL = "https://www.wixapis.com/promote-seo-robots-server/v2/ads"
WIX_QUERY_SITES_URL = "https://www.wixapis.com/site-list/v2/sites/query"
TELEGRAM_SUCCESS_MESSAGE = (
    "✅ Обновил ads файлы KidsGames\n"
    "kidsgames.top/app-ads.txt\n"
    "kidsgames.top/ads.txt"
)

VERIFY_URLS = (
    "https://www.kidsgames.top/ads.txt",
    "https://www.kidsgames.top/app-ads.txt",
)

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

SOURCE_ENV_PREFIXES = {
    "bigo": "BIGO",
    "bidmachine": "BIDMACHINE",
    "dtexchange": "DTEXCHANGE",
    "inmobi": "INMOBI",
    "ironsource": "IRONSOURCE",
    "mintegral": "MINTEGRAL",
    "unity": "UNITY",
    "yandex": "YANDEX",
    "yandex2": "YANDEX2",
    "yandex_add": "YANDEX_ADD",
    "liftoff": "VUNGLE",
    "vungle": "VUNGLE",
}

MINTEGRAL_MARKER = "Please replace your PublisherID with your actual publisher id acquired from Mintegral dashboard."
MINTEGRAL_PUBLISHER_ID = "47780"
MINTEGRAL_DOC_MENU_URL = "https://cdn-adn.rayjump.com/cdn-adn/v2/markdown_v2/js/file_v2.js"
MINTEGRAL_DOC_BASE_URLS = (
    "https://cdn-mtg-markdown.rayjump.com/cdn-adn/v2/markdown_v2/docs",
    "https://cdn-adn-https-new.rayjump.com/cdn-adn/v2/markdown_v2/docs",
)
MINTEGRAL_DOC_KEY = "sdk-m_sdk-about_ads"
MINTEGRAL_DOC_LANG = "en"
MINTEGRAL_MARKER_PATTERN = re.compile(
    r"please\s+replace\s+your\s+publisherid\s+with\s+your\s+actual\s+publisher\s+id\s+acquired\s+from\s+mintegral\s+dashboard\.?",
    re.IGNORECASE,
)
VUNGLE_SOURCE_URL = "https://pub-ctrl-api.vungle.com/api/v1/adstxt/vungle"
VUNGLE_FIRST_LINE = "vungle.com,669477b160e2ea00114a81e3,DIRECT,c107d686becd2d77"
BIGO_SOURCE_URL = "https://www.bigossp.com/union/app-ads-txt/developer/list"
BIDMACHINE_SOURCE_URL = "https://dashboard.bidmachine.io/app-ads/file/sellerId=789"
DTEXCHANGE_SOURCE_URL = "https://www.digitalturbine.com/dt-app-ads.txt"
DTEXCHANGE_FIRST_LINE = "fyber.com,230573,DIRECT,1ad675c9de6b5176"
INMOBI_SOURCE_URL = "https://publisher.inmobi.com/ads-txt/app-ads"
INMOBI_MARKER_PATTERN = re.compile(
    r"once\s+selected,\s+copy\s+the\s+lines\s+into\s+your\s+app-ads\.txt\s+of\s+apps\s+listed\s+in\s+adjacent\s+section",
    re.IGNORECASE,
)
IRONSOURCE_SOURCE_URL = "https://docs.unity.com/en-us/grow/is-ads/user-acquisition/ironsource-exchange/app-ads-txt"
IRONSOURCE_FIRST_LINE = "ironsrc.com, 338629, Direct"
IRONSOURCE_OWNER_DOMAIN_LINE = "OwnerDomain=kidsgames.top"
IRONSOURCE_MARKER_PATTERN = re.compile(r"ironsource\s+authorized\s+resellers", re.IGNORECASE)
YANDEX_SOURCE_URL = "https://partner.yandex.ru/restapi/v1/api/files/sellers/app-ads.txt"
YANDEX2_FIRST_LINES = (
    "yango-ads.com, 104716934, DIRECT",
    "yango-ads.com, 97637571, DIRECT",
    "yango-ads.com, 1079241, DIRECT",
    "yango-ads.com, 305746111, DIRECT",
)
ADS_LINE_PATTERN = re.compile(
    r"([a-z0-9.-]+\.[a-z]{2,}\s*,\s*(?:your\s+PublisherID|[^,\s<]+)\s*,\s*(?:DIRECT|RESELLER)(?:\s*,\s*[^,\s<]+)?)",
    re.IGNORECASE,
)


KIDSGAMES_LINES = (
    "# KidsGames Last updated {date_text}",
    "google.com, pub-2206193735487862, DIRECT, f08c47fec0942fa0",
    "facebook.com, 982473989127847, DIRECT, c3e20eee3f780d68",
    "applovin.com, 3924b154e4c887949b692faf5649901d, DIRECT",
    "rubiconproject.com, 16356, RESELLER, 0bfd66d529a55807",
    "openx.com, 540785403, RESELLER, 6a698e2ec38604c6",
    "indexexchange.com, 191086, RESELLER",
    "pubmatic.com, 158862, RESELLER, 5d62403b186f2ace",
    "pubnative.net, 1007170, RESELLER, d641df8625486a7b",
    "verve.com, 15290, RESELLER, 0c8f5958fc2d6270",
    "mangomob.net, 5000671859, DIRECT",
    "",
)


@dataclass(frozen=True)
class Settings:
    source_url: str
    timezone: str
    ftp_host: str | None
    ftp_port: int
    ftp_user: str | None
    ftp_password: str | None
    ftp_remote_dir: str
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    wix_api_key: str | None
    wix_site_id: str | None
    wix_account_id: str | None
    wix_enabled: bool
    notifications_enabled: bool
    verify_urls: tuple[str, ...]
    extra_source_names: tuple[str, ...]


@dataclass(frozen=True)
class SourceAccess:
    name: str
    url: str
    login: str | None
    password: str | None
    headers: dict[str, str]
    use_basic_auth: bool
    method: str
    payload: bytes | None


def month_day_year(value: date) -> str:
    return f"{value.strftime('%B')} {value.day}, {value.year}"


def get_timezone(name: str) -> tzinfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        if name == DEFAULT_TIMEZONE:
            logging.warning("Timezone database is unavailable; using UTC+02:00 fallback.")
            return timezone(timedelta(hours=2))
        raise


def setup_logging(verbose: bool) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    level = logging.DEBUG if verbose else logging.INFO
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)


def env_settings() -> Settings:
    def env(name: str, default: str | None = None) -> str | None:
        return os.getenv(name) or default

    verify_urls = tuple(
        item.strip()
        for item in env("VERIFY_URLS", ",".join(VERIFY_URLS)).split(",")
        if item.strip()
    )
    extra_source_names = tuple(
        item.strip().lower()
        for item in env("EXTRA_SOURCES", "").split(",")
        if item.strip()
    )
    return Settings(
        source_url=env("SOURCE_URL", SOURCE_URL),
        timezone=env("APP_TIMEZONE", DEFAULT_TIMEZONE),
        ftp_host=env("FTP_HOST"),
        ftp_port=int(env("FTP_PORT", "21")),
        ftp_user=env("FTP_USER"),
        ftp_password=env("FTP_PASSWORD"),
        ftp_remote_dir=env("FTP_REMOTE_DIR", DEFAULT_FTP_REMOTE_DIR),
        telegram_bot_token=env("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=env("TELEGRAM_CHAT_ID"),
        wix_api_key=env("WIX_API_KEY") or env("WIX_API_KEY2"),
        wix_site_id=env("WIX_SITE_ID"),
        wix_account_id=env("WIX_ACCOUNT_ID"),
        wix_enabled=(env("WIX_ENABLED", "false") or "").lower() == "true",
        notifications_enabled=(env("NOTIFICATIONS_ENABLED", "false") or "").lower() == "true",
        verify_urls=verify_urls,
        extra_source_names=extra_source_names,
    )


def fetch_text(
    url: str,
    timeout: int = 30,
    login: str | None = None,
    password: str | None = None,
    extra_headers: dict[str, str] | None = None,
    use_basic_auth: bool = True,
    method: str = "GET",
    payload: bytes | None = None,
) -> str:
    headers = {"User-Agent": "KidsGames-app-ads-updater/1.0"}
    if extra_headers:
        headers.update(extra_headers)
    if use_basic_auth and login and password and "Authorization" not in headers:
        headers["Authorization"] = basic_authorization(login, password)
    request = Request(url, data=payload, headers=headers, method=method)
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8-sig")


def source_access_from_env(source_name: str) -> SourceAccess:
    key = source_name.strip().lower()
    prefix = SOURCE_ENV_PREFIXES.get(key)
    if not prefix:
        known = ", ".join(sorted(SOURCE_ENV_PREFIXES))
        raise RuntimeError(f"Unknown source {source_name!r}. Known sources: {known}")

    url = os.getenv(f"{prefix}_SOURCE_URL")
    if key == "bigo":
        url = url or BIGO_SOURCE_URL
    if key == "bidmachine":
        url = url or BIDMACHINE_SOURCE_URL
    if key == "dtexchange":
        url = url or DTEXCHANGE_SOURCE_URL
    if key == "inmobi":
        url = url or INMOBI_SOURCE_URL
    if key == "ironsource":
        url = url or IRONSOURCE_SOURCE_URL
    if key in {"yandex", "yandex2", "yandex_add"}:
        yandex_url = os.getenv(f"{prefix}_URL")
        url = url or (None if is_yandex_oauth_url(yandex_url) else yandex_url) or YANDEX_SOURCE_URL
    if key in {"liftoff", "vungle"}:
        url = url or VUNGLE_SOURCE_URL
    if not url:
        raise RuntimeError(f"Missing source secret: {prefix}_SOURCE_URL")

    headers = source_headers_from_env(prefix)
    method = "GET"
    payload = None
    if key == "bigo":
        bigo_token = os.getenv("BIGO_TOKEN")
        bigo_token2 = os.getenv("BIGO_TOKEN2")
        if bigo_token:
            headers[os.getenv("BIGO_TOKEN_HEADER", "x-auth-token")] = bigo_token
        if bigo_token2:
            headers[os.getenv("BIGO_TOKEN2_HEADER", "bigo-ads-uid")] = bigo_token2
        headers.setdefault("Accept", "application/json, text/plain, */*")
        headers.setdefault("Content-Type", "application/json")
        headers.setdefault("Origin", "https://www.bigossp.com")
        headers.setdefault("Referer", "https://www.bigossp.com/media/appAdsTxt/developer")
        method = "POST"
        payload = (os.getenv("BIGO_PAYLOAD") or "{}").encode("utf-8")
    elif key == "bidmachine":
        bidmachine_token = os.getenv("BIDMACHINE_TOKEN")
        if bidmachine_token:
            headers[os.getenv("BIDMACHINE_TOKEN_HEADER", "X-Auth-Token")] = bidmachine_token
        headers.setdefault("Accept", "text/plain, */*")
        headers.setdefault("Referer", "https://dashboard.bidmachine.io/")
    elif key == "unity":
        unity_name = os.getenv("UNITY_NAME")
        unity_token = os.getenv("UNITY_TOKEN")
        unity_auth = os.getenv("UNITY_AUTH") or os.getenv("UNITYADS_AUTH")
        if unity_auth:
            headers["Authorization"] = authorization_header(unity_auth)
        if "Authorization" in headers:
            pass
        elif unity_name and unity_token:
            headers["Authorization"] = basic_authorization(unity_name, unity_token)
        elif unity_token:
            headers["Authorization"] = f"Bearer {unity_token}"
        headers.setdefault("Accept", "application/json, text/plain, */*")
        headers.setdefault("Content-Type", "application/json")
        headers.setdefault("Origin", "https://cloud.unity.com")
        headers.setdefault("x-client-id", "unity-dashboard")
        method = "POST"
        publisher_web_url = os.getenv("UNITY_PUBLISHER_WEB_URL", "https://www.kidsgames.top/app-ads.txt")
        payload = json.dumps({"publisherWebUrl": publisher_web_url}).encode("utf-8")
    elif key in {"liftoff", "vungle"}:
        headers.setdefault("Accept", "text/plain, */*")
    elif key == "inmobi":
        headers.setdefault("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.7")
    elif key in {"yandex", "yandex2", "yandex_add"}:
        token = yandex_access_token_from_env(prefix)
        if token and "Authorization" not in headers:
            headers["Authorization"] = token if token.lower().startswith(("oauth ", "bearer ")) else f"OAuth {token}"
        headers.setdefault("Accept", "application/json, text/plain, */*")
        headers.setdefault("Referer", "https://partner.yandex.ru/")

    return SourceAccess(
        name=key,
        url=url,
        login=os.getenv(f"{prefix}_LOGIN"),
        password=os.getenv(f"{prefix}_PASSWORD"),
        headers=headers,
        use_basic_auth=key not in {"inmobi", "unity", "yandex", "yandex2", "yandex_add"},
        method=method,
        payload=payload,
    )


def source_headers_from_env(prefix: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    authorization = os.getenv(f"{prefix}_AUTHORIZATION")
    cookie = os.getenv(f"{prefix}_COOKIE")
    if authorization:
        headers["Authorization"] = authorization
    if cookie:
        headers["Cookie"] = cookie
    return headers


def basic_authorization(login: str, password: str) -> str:
    token = base64.b64encode(f"{login}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def authorization_header(value: str) -> str:
    return value if value.lower().startswith(("basic ", "bearer ")) else f"Bearer {value}"


def is_yandex_oauth_url(url: str | None) -> bool:
    if not url:
        return False
    host = urlparse(url).netloc.lower()
    return host.endswith("oauth.yandex.ru") or host.endswith("passport.yandex.ru")


def yandex_access_token_from_env(prefix: str = "YANDEX") -> str | None:
    explicit_token = os.getenv(f"{prefix}_ACCESS_TOKEN") or os.getenv(f"{prefix}_TOKEN")
    if explicit_token:
        return explicit_token

    yandex_url = os.getenv(f"{prefix}_URL")
    if yandex_url:
        parsed_url = urlparse(yandex_url)
        url_params = parse_qs(parsed_url.query)
        fragment_params = parse_qs(parsed_url.fragment)
        token_values = fragment_params.get("access_token") or url_params.get("access_token")
        if token_values and token_values[0]:
            return token_values[0]

    code = os.getenv(f"{prefix}_CODE") or yandex_oauth_code_from_url(yandex_url)
    refresh_token = os.getenv(f"{prefix}_REFRESH_TOKEN")
    if code or refresh_token:
        return fetch_yandex_oauth_token(prefix, code=code, refresh_token=refresh_token)

    return None


def yandex_oauth_code_from_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed_url = urlparse(url)
    code_values = parse_qs(parsed_url.query).get("code")
    return code_values[0] if code_values else None


def fetch_yandex_oauth_token(prefix: str = "YANDEX", code: str | None = None, refresh_token: str | None = None) -> str:
    client_id = os.getenv(f"{prefix}_CLIENT_ID")
    client_secret = os.getenv(f"{prefix}_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError(f"{prefix}_CLIENT_ID and {prefix}_CLIENT_SECRET are required to request a Yandex OAuth token.")

    form: dict[str, str] = {
        "client_id": client_id,
        "client_secret": client_secret,
    }
    if refresh_token:
        form["grant_type"] = "refresh_token"
        form["refresh_token"] = refresh_token
    elif code:
        form["grant_type"] = "authorization_code"
        form["code"] = code
    else:
        raise RuntimeError("YANDEX_CODE or YANDEX_REFRESH_TOKEN is required to request a Yandex OAuth token.")

    request = Request(
        "https://oauth.yandex.ru/token",
        data=urlencode(form).encode("utf-8"),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": "KidsGames-app-ads-updater/1.0",
        },
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8-sig"))
    access_token = payload.get("access_token") if isinstance(payload, dict) else None
    if not isinstance(access_token, str) or not access_token:
        raise RuntimeError(f"Yandex OAuth response does not contain access_token: {payload}")
    return access_token


def looks_like_ads_txt(text: str) -> bool:
    stripped = text.lstrip()
    if stripped.lower().startswith(("<!doctype html", "<html")) or stripped.startswith(("{", "[")):
        return False

    for line in text.splitlines():
        candidate = line.strip()
        if not candidate or candidate.startswith("#"):
            continue
        parts = [part.strip() for part in candidate.split(",")]
        if len(parts) >= 3 and parts[2].upper() in {"DIRECT", "RESELLER"}:
            return True
    return False


def is_ads_txt_line(line: str) -> bool:
    parts = [part.strip() for part in line.split(",")]
    return (
        len(parts) >= 3
        and re.fullmatch(r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}", parts[0]) is not None
        and parts[2].upper() in {"DIRECT", "RESELLER"}
    )


def html_to_text(value: str) -> str:
    with_breaks = re.sub(r"(?i)<\s*(pre|code|textarea)(?:\s[^>]*)?>", "\n```\n", value)
    with_breaks = re.sub(r"(?i)</\s*(pre|code|textarea)\s*>", "\n```\n", with_breaks)
    with_breaks = re.sub(r"(?i)<\s*br\s*/?\s*>", "\n", with_breaks)
    with_breaks = re.sub(r"(?i)</\s*(p|div|tr|li)\s*>", "\n", with_breaks)
    without_tags = re.sub(r"<[^>]+>", "", with_breaks)
    return html.unescape(without_tags)


def replace_mintegral_publisher_id(line: str) -> str:
    return re.sub(r"your\s+PublisherID", MINTEGRAL_PUBLISHER_ID, line, flags=re.IGNORECASE)


def is_mintegral_block_line(line: str) -> bool:
    return is_ads_txt_line(line) or line.lower().startswith("inventorypartnerdomain=")


def extract_mintegral_ads_txt(raw_text: str) -> str:
    text = html_to_text(raw_text) if raw_text.lstrip().lower().startswith(("<!doctype html", "<html")) else raw_text
    marker_match = MINTEGRAL_MARKER_PATTERN.search(text)
    regex_only = False
    if marker_match:
        after_marker = text[marker_match.end() :]
    else:
        publisher_id_index = text.lower().find("your publisherid")
        if publisher_id_index < 0:
            if looks_like_ads_txt(text):
                after_marker = text
            else:
                preview_lines = [line.strip() for line in text.splitlines() if line.strip()][:10]
                preview = " | ".join(line[:160] for line in preview_lines)
                raise RuntimeError(f"Mintegral marker text was not found in source page. Text preview: {preview}")
        else:
            line_start = text.rfind("\n", 0, publisher_id_index) + 1
            after_marker = text[line_start:]
    output_lines: list[str] = []

    if not regex_only:
        collecting = False
        inside_fence = False
        for raw_line in after_marker.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("```"):
                inside_fence = not inside_fence
                continue
            line = replace_mintegral_publisher_id(line)
            if not collecting and not is_mintegral_block_line(line):
                continue
            if collecting and not is_mintegral_block_line(line):
                continue
            collecting = True
            output_lines.append(line)

    if not output_lines:
        output_lines = []
        for match in ADS_LINE_PATTERN.finditer(after_marker):
            line = " ".join(match.group(1).strip().split())
            line = replace_mintegral_publisher_id(line)
            output_lines.append(line)

    if not output_lines:
        raise RuntimeError("Mintegral ads block was found, but no app-ads.txt lines were extracted.")

    return "\n".join(output_lines) + "\n"


def mintegral_doc_path_from_menu(menu_text: str, doc_key: str, lang: str) -> str:
    match = re.search(r"var\s+docSet\s*=\s*(\[.*?\]);", menu_text, re.DOTALL)
    if not match:
        raise RuntimeError("Could not find Mintegral docSet menu data.")

    nodes = json.loads(match.group(1))
    current_nodes: object = nodes
    for key in doc_key.split("-"):
        if not isinstance(current_nodes, list):
            raise RuntimeError(f"Could not resolve Mintegral doc key: {doc_key}")
        node = next((item for item in current_nodes if isinstance(item, dict) and item.get("key") == key), None)
        if not isinstance(node, dict):
            raise RuntimeError(f"Could not resolve Mintegral doc key: {doc_key}")
        current_nodes = node.get("data") or node.get("language") or []

    if not isinstance(current_nodes, list):
        raise RuntimeError(f"Could not resolve Mintegral doc language: {lang}")
    language = next((item for item in current_nodes if isinstance(item, dict) and item.get("key") == lang), None)
    if not isinstance(language, dict) or not isinstance(language.get("path"), str):
        raise RuntimeError(f"Could not resolve Mintegral doc language: {lang}")
    return language["path"]


def fetch_mintegral_markdown_doc(source: SourceAccess) -> str:
    menu_text = fetch_text(
        MINTEGRAL_DOC_MENU_URL,
        login=source.login,
        password=source.password,
        extra_headers=source.headers,
        use_basic_auth=source.use_basic_auth,
        method=source.method,
        payload=source.payload,
    )
    doc_path = mintegral_doc_path_from_menu(menu_text, MINTEGRAL_DOC_KEY, MINTEGRAL_DOC_LANG)
    errors: list[str] = []
    for base_url in MINTEGRAL_DOC_BASE_URLS:
        doc_url = f"{base_url}/{doc_path}/index.md"
        try:
            logging.info("Fetching Mintegral markdown doc %s.", doc_url)
            return fetch_text(
                doc_url,
                login=source.login,
                password=source.password,
                extra_headers=source.headers,
                use_basic_auth=source.use_basic_auth,
            )
        except (HTTPError, URLError, TimeoutError) as exc:
            errors.append(f"{doc_url}: {exc}")
    raise RuntimeError("Could not fetch Mintegral markdown doc. " + " | ".join(errors))


def linked_javascript_urls(page_url: str, html_text: str) -> list[str]:
    urls: list[str] = []
    for match in re.finditer(r"""(?i)<script[^>]+src=["']([^"']+)["']""", html_text):
        raw_url = html.unescape(match.group(1)).strip()
        if any(ord(char) < 32 for char in raw_url) or any(char.isspace() for char in raw_url):
            continue
        url = urljoin(page_url, raw_url)
        if url not in urls:
            urls.append(url)
    for match in re.finditer(r"""["']([^"']+\.js(?:\?[^"']*)?)["']""", html_text, re.IGNORECASE):
        raw_url = html.unescape(match.group(1)).strip()
        if any(ord(char) < 32 for char in raw_url) or any(char.isspace() for char in raw_url):
            continue
        url = urljoin(page_url, raw_url)
        if url not in urls:
            urls.append(url)
    return urls


def decode_javascript_unicode_escapes(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        return chr(int(match.group(1), 16))

    return re.sub(r"\\u([0-9a-fA-F]{4})", replace, value)


def extract_mintegral_source_text(source: SourceAccess, raw_text: str) -> str:
    try:
        return extract_mintegral_ads_txt(raw_text)
    except RuntimeError as first_error:
        scripts = linked_javascript_urls(source.url, raw_text)
        if not scripts:
            try:
                markdown_text = fetch_mintegral_markdown_doc(source)
                return extract_mintegral_ads_txt(markdown_text)
            except RuntimeError:
                raise first_error

        logging.info("Mintegral block was not in the page HTML; checking linked script chunks.")
        script_texts: list[str] = []
        seen_scripts: set[str] = set()
        script_index = 0
        while script_index < len(scripts) and len(seen_scripts) < 100:
            script_url = scripts[script_index]
            script_index += 1
            if script_url in seen_scripts:
                continue
            seen_scripts.add(script_url)
            try:
                script_text = fetch_text(
                    script_url,
                    login=source.login,
                    password=source.password,
                    extra_headers=source.headers,
                    use_basic_auth=source.use_basic_auth,
                )
            except (HTTPError, URLError, TimeoutError, ValueError) as exc:
                logging.warning("Could not fetch Mintegral script %s: %s", script_url, exc)
                continue
            decoded_script = decode_javascript_unicode_escapes(script_text)
            script_texts.append(decoded_script)
            for nested_url in linked_javascript_urls(script_url, decoded_script):
                if nested_url not in seen_scripts and nested_url not in scripts:
                    scripts.append(nested_url)
        logging.info("Checked %s Mintegral script chunk(s).", len(seen_scripts))

        if not script_texts:
            raise first_error
        combined_text = raw_text + "\n" + "\n".join(script_texts)
        try:
            return extract_mintegral_ads_txt(combined_text)
        except RuntimeError:
            try:
                markdown_text = fetch_mintegral_markdown_doc(source)
                return extract_mintegral_ads_txt(markdown_text)
            except RuntimeError:
                raise first_error


def extract_source_text(source: SourceAccess, raw_text: str) -> str:
    if source.name == "bigo":
        return extract_bigo_source_text(raw_text)
    if source.name == "bidmachine":
        return extract_bidmachine_source_text(raw_text)
    if source.name == "dtexchange":
        return extract_dtexchange_source_text(raw_text)
    if source.name == "inmobi":
        return extract_inmobi_source_text(raw_text)
    if source.name == "ironsource":
        return extract_ironsource_source_text(raw_text)
    if source.name == "mintegral":
        return extract_mintegral_source_text(source, raw_text)
    if source.name == "unity":
        return extract_unity_source_text(raw_text)
    if source.name == "yandex2":
        return extract_yandex_source_text(raw_text, first_lines=YANDEX2_FIRST_LINES)
    if source.name in {"yandex", "yandex_add"}:
        return extract_yandex_source_text(raw_text)
    if source.name in {"liftoff", "vungle"}:
        return extract_vungle_source_text(raw_text)
    return raw_text


def source_text_from_lines(lines: Iterable[str]) -> str:
    output_lines = [line.strip() for line in lines if line.strip()]
    if not any(is_ads_txt_line(line) for line in output_lines):
        raise RuntimeError("No app-ads.txt lines were extracted.")
    return "\n".join(output_lines) + "\n"


def extract_bigo_source_text(raw_text: str) -> str:
    if looks_like_ads_txt(raw_text):
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        return "\n".join(lines) + "\n"

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        preview_lines = [line.strip() for line in raw_text.splitlines() if line.strip()][:10]
        preview = " | ".join(line[:160] for line in preview_lines)
        raise RuntimeError(f"Bigo source is not app-ads.txt text or JSON. Text preview: {preview}") from exc

    lines = extract_ads_lines_from_json_value(payload)
    if not lines:
        raise RuntimeError(f"Bigo JSON response does not contain app-ads.txt lines: {payload}")
    return "\n".join(line.strip() for line in lines if line.strip()) + "\n"


def extract_bidmachine_source_text(raw_text: str) -> str:
    if raw_text.lstrip().lower().startswith(("<!doctype html", "<html")):
        raise RuntimeError("BidMachine returned the dashboard HTML shell instead of app-ads.txt; provide BIDMACHINE_TOKEN from localStorage access-token or the X-Auth-Token request header.")

    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if not lines or not any(is_ads_txt_line(line) for line in lines):
        preview = " | ".join(line[:160] for line in lines[:10])
        raise RuntimeError(f"BidMachine source does not contain app-ads.txt lines. Text preview: {preview}")

    return "\n".join(lines) + "\n"


def extract_dtexchange_source_text(raw_text: str) -> str:
    lines = [line.strip() for line in raw_text.splitlines()]
    meaningful_lines = [line for line in lines if line]
    if len(meaningful_lines) < 2:
        raise RuntimeError("DT Exchange source has fewer than two lines.")
    if not meaningful_lines[0].lower().startswith("resellers as of "):
        raise RuntimeError(f"DT Exchange source first line is unexpected: {meaningful_lines[0]!r}")

    output_lines = [DTEXCHANGE_FIRST_LINE]
    for line in meaningful_lines[2:]:
        output_lines.append(line)

    if len(output_lines) == 1:
        raise RuntimeError("DT Exchange source was found, but no reseller lines were extracted.")

    return "\n".join(output_lines) + "\n"


def extract_inmobi_source_text(raw_text: str) -> str:
    if looks_like_ads_txt(raw_text):
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        return "\n".join(lines) + "\n"

    if "loginUrl" in raw_text and "iam.inmobi.com" in raw_text:
        raise RuntimeError("InMobi returned the login shell instead of the sellers list; provide INMOBI_COOKIE or INMOBI_AUTHORIZATION for an authenticated session.")

    candidate_lines: list[str] = []
    if raw_text.lstrip().lower().startswith(("<!doctype html", "<html")):
        html_marker_match = INMOBI_MARKER_PATTERN.search(raw_text)
        if html_marker_match:
            after_marker_html = raw_text[html_marker_match.end() :]
            pre_match = re.search(r"(?is)<pre\b[^>]*>(.*?)</pre>", after_marker_html)
            code_area = pre_match.group(1) if pre_match else after_marker_html
            candidate_lines = [
                html.unescape(re.sub(r"<[^>]+>", "", match.group(1))).strip()
                for match in re.finditer(r"(?is)<span\b[^>]*(?:Typography-code|code)[^>]*>(.*?)</span>", code_area)
            ]

    text = html_to_text(raw_text) if raw_text.lstrip().lower().startswith(("<!doctype html", "<html")) else raw_text
    marker_match = INMOBI_MARKER_PATTERN.search(text)
    if marker_match and not candidate_lines:
        after_marker = text[marker_match.end() :]
        candidate_lines = [line.strip() for line in after_marker.splitlines()]
    elif not marker_match and not candidate_lines:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        candidate_lines = lines if any(is_ads_txt_line(line) for line in lines) else []

    output_lines = [line for line in candidate_lines if line and is_ads_txt_line(line)]
    if not output_lines:
        preview_lines = [line.strip() for line in text.splitlines() if line.strip()][:10]
        preview = " | ".join(line[:160] for line in preview_lines)
        raise RuntimeError(f"InMobi seller block was not found or contained no app-ads.txt lines. Text preview: {preview}")

    return "\n".join(output_lines) + "\n"


def extract_ironsource_source_text(raw_text: str) -> str:
    text = html_to_text(raw_text) if raw_text.lstrip().lower().startswith(("<!doctype html", "<html")) else raw_text
    marker_match = IRONSOURCE_MARKER_PATTERN.search(text)
    if not marker_match:
        preview_lines = [line.strip() for line in text.splitlines() if line.strip()][:10]
        preview = " | ".join(line[:160] for line in preview_lines)
        raise RuntimeError(f"ironSource authorized resellers marker was not found. Text preview: {preview}")

    after_marker = text[marker_match.end() :]
    output_lines = [IRONSOURCE_FIRST_LINE, IRONSOURCE_OWNER_DOMAIN_LINE]

    candidate_lines: list[str] = []
    if raw_text.lstrip().lower().startswith(("<!doctype html", "<html")):
        html_marker_match = IRONSOURCE_MARKER_PATTERN.search(raw_text)
        if html_marker_match:
            pre_match = re.search(r"(?is)<pre\b[^>]*>(.*?)</pre>", raw_text[html_marker_match.end() :])
            if pre_match:
                candidate_lines = [
                    html.unescape(re.sub(r"<[^>]+>", "", match.group(1))).strip()
                    for match in re.finditer(r"(?is)<span\b[^>]*Typography-code[^>]*>(.*?)</span>", pre_match.group(1))
                ]

    if not candidate_lines:
        candidate_lines = [" ".join(match.group(1).strip().split()) for match in ADS_LINE_PATTERN.finditer(after_marker)]

    for line in candidate_lines:
        line = line.strip()
        if not is_ads_txt_line(line):
            continue
        domain = line.split(",", 1)[0].strip().lower()
        if domain == "ironsrc.com":
            continue
        output_lines.append(line)

    if len(output_lines) == 2:
        raise RuntimeError("ironSource reseller block was found, but no reseller lines were extracted.")

    return "\n".join(output_lines) + "\n"


def extract_vungle_source_text(raw_text: str) -> str:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        pass
    else:
        value = payload.get("value") if isinstance(payload, dict) else None
        if not isinstance(value, str):
            raise RuntimeError(f"Vungle JSON response does not contain app-ads.txt value: {payload}")
        raw_text = value

    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("Vungle source is empty.")
    invalid_lines = [
        line
        for line in lines[1:]
        if not (
            is_ads_txt_line(line)
            or line.startswith("#")
            or line.lower().startswith(("ownerdomain=", "managerdomain=", "inventorypartnerdomain="))
        )
    ]
    if invalid_lines:
        preview = " | ".join(line[:160] for line in invalid_lines[:3])
        raise RuntimeError(f"Vungle source does not look like an app-ads.txt file. Unexpected lines: {preview}")
    lines[0] = VUNGLE_FIRST_LINE
    return "\n".join(lines) + "\n"


def extract_ads_lines_from_json_value(value: object) -> list[str]:
    lines: list[str] = []
    if isinstance(value, str):
        for line in value.splitlines():
            if is_ads_txt_line(line.strip()):
                lines.append(line)
    elif isinstance(value, list):
        for item in value:
            lines.extend(extract_ads_lines_from_json_value(item))
    elif isinstance(value, dict):
        for item in value.values():
            lines.extend(extract_ads_lines_from_json_value(item))
    return lines


def extract_unity_source_text(raw_text: str) -> str:
    if looks_like_ads_txt(raw_text):
        return source_text_from_lines(raw_text.splitlines())

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        text = html_to_text(raw_text) if raw_text.lstrip().lower().startswith(("<!doctype html", "<html")) else raw_text
        lines = extract_ads_lines_from_json_value(text)
        if lines:
            return source_text_from_lines(lines)
        preview_lines = [line.strip() for line in text.splitlines() if line.strip()][:10]
        preview = " | ".join(line[:160] for line in preview_lines)
        raise RuntimeError(f"Unity source is not app-ads.txt text, JSON, or HTML with app-ads.txt lines. Text preview: {preview}") from exc

    lines = extract_ads_lines_from_json_value(payload)
    if not lines:
        raise RuntimeError(f"Unity JSON response does not contain app-ads.txt lines: {payload}")
    return source_text_from_lines(lines)


def extract_yandex_source_text(raw_text: str, first_lines: Iterable[str] = ()) -> str:
    if looks_like_ads_txt(raw_text):
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        return "\n".join([*first_lines, *lines]) + "\n"

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        payload = None
    if payload is not None:
        lines = extract_ads_lines_from_json_value(payload)
        if lines:
            return "\n".join([*first_lines, *(line.strip() for line in lines if line.strip())]) + "\n"

    text = html_to_text(raw_text) if raw_text.lstrip().lower().startswith(("<!doctype html", "<html")) else raw_text
    lower_text = text.lower()
    if "passport.yandex" in lower_text or "mode=auth" in lower_text:
        raise RuntimeError("Yandex returned the login page instead of app-ads.txt lines; provide a valid YANDEX_ACCESS_TOKEN, YANDEX_TOKEN, YANDEX_AUTHORIZATION, YANDEX_CODE, or YANDEX_REFRESH_TOKEN.")

    lines = [" ".join(match.group(1).strip().split()) for match in ADS_LINE_PATTERN.finditer(text)]
    if not lines:
        preview_lines = [line.strip() for line in text.splitlines() if line.strip()][:10]
        preview = " | ".join(line[:160] for line in preview_lines)
        raise RuntimeError(f"Yandex source does not contain app-ads.txt lines. Text preview: {preview}")
    return "\n".join([*first_lines, *lines]) + "\n"


def test_source_access(source_name: str) -> None:
    source = source_access_from_env(source_name)
    has_auth_headers = any(
        header.lower() in {"authorization", "cookie", "x-auth-token", "bigo-ads-uid"}
        for header in source.headers
    )
    if source.name == "unity" and "Authorization" in source.headers and (os.getenv("UNITYADS_AUTH") or os.getenv("UNITY_AUTH") or os.getenv("UNITY_AUTHORIZATION")):
        auth_state = "with UNITY_AUTH"
    elif source.name == "unity" and os.getenv("UNITY_NAME") and os.getenv("UNITY_TOKEN"):
        auth_state = "with UNITY_NAME/UNITY_TOKEN basic auth"
    elif source.name == "unity" and os.getenv("UNITY_TOKEN"):
        auth_state = "with UNITY_TOKEN bearer auth"
    elif has_auth_headers:
        auth_state = "with custom headers"
    elif source.use_basic_auth and source.login and source.password:
        auth_state = "with login/password"
    else:
        auth_state = "without auth"
    logging.info("Testing %s source access %s.", source.name, auth_state)
    parsed_url = urlparse(source.url)
    logging.info("Testing %s endpoint %s%s.", source.name, parsed_url.netloc, parsed_url.path)
    try:
        raw_text = fetch_text(
            source.url,
            login=source.login,
            password=source.password,
            extra_headers=source.headers,
            use_basic_auth=source.use_basic_auth,
            method=source.method,
            payload=source.payload,
        )
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        preview = " | ".join(line.strip() for line in error_body.splitlines() if line.strip())[:500]
        raise RuntimeError(f"{source.name} source HTTP {exc.code}: {preview}") from exc
    text = extract_source_text(source, raw_text)
    lines = text.splitlines()
    if not looks_like_ads_txt(text):
        preview = " | ".join(line[:120] for line in lines[:3])
        raise RuntimeError(f"{source.name} source does not look like app-ads.txt. First lines: {preview}")
    write_cached_source_text(source.name, text)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    logging.info(
        "%s source fetched successfully: %s bytes, %s lines, sha256=%s",
        source.name,
        len(text.encode("utf-8")),
        len(lines),
        digest,
    )
    for index, line in enumerate(lines[:5], start=1):
        logging.info("%s line %s: %s", source.name, index, line[:300])
    if len(lines) > 5:
        tail = lines[-5:]
        tail_start = len(lines) - len(tail) + 1
        for index, line in enumerate(tail, start=tail_start):
            logging.info("%s line %s: %s", source.name, index, line[:300])


def parse_date_from_line(line: str) -> date | None:
    iso = re.search(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", line)
    if iso:
        return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))

    month_first = re.search(
        r"\b("
        + "|".join(MONTHS)
        + r")\s+(\d{1,2})(?:st|nd|rd|th)?[,]?\s+(20\d{2})\b",
        line,
        re.IGNORECASE,
    )
    if month_first:
        return date(
            int(month_first.group(3)),
            MONTHS[month_first.group(1).lower()],
            int(month_first.group(2)),
        )

    day_first = re.search(
        r"\b(\d{1,2})(?:st|nd|rd|th)?\s+("
        + "|".join(MONTHS)
        + r")[,]?\s+(20\d{2})\b",
        line,
        re.IGNORECASE,
    )
    if day_first:
        return date(
            int(day_first.group(3)),
            MONTHS[day_first.group(2).lower()],
            int(day_first.group(1)),
        )

    return None


def source_is_current(first_line: str, today: date) -> bool:
    source_date = parse_date_from_line(first_line)
    if source_date is None:
        logging.warning("No date found in source first line: %r", first_line)
        return False
    return source_date in {today, today + timedelta(days=1)}


def build_output(source_text: str, today: date, extra_source_texts: Iterable[tuple[str, str]] = ()) -> str:
    source_lines = source_text.splitlines()
    if len(source_lines) < 2:
        raise ValueError("Source app-ads.txt has fewer than two lines.")

    source_lines[1] = "OwnerDomain=kidsgames.top"
    kidsgames_text = "\n".join(line.format(date_text=month_day_year(today)) for line in KIDSGAMES_LINES)
    source_part = "\n".join(source_lines)
    extra_parts: list[str] = []
    for name, text in extra_source_texts:
        cleaned = text.strip()
        if cleaned:
            extra_parts.append(f"# {name} app-ads.txt\n{cleaned}")
    extra_text = "\n\n".join(extra_parts)
    if extra_text:
        return f"{kidsgames_text}\n{source_part}\n\n{extra_text}\n"
    return f"{kidsgames_text}\n{source_part}\n"


def source_cache_path(source_name: str) -> Path:
    safe_name = re.sub(r"[^a-z0-9_.-]+", "-", source_name.strip().lower())
    return SOURCE_CACHE_DIR / f"{safe_name}.txt"


def read_cached_source_text(source_name: str) -> str | None:
    path = source_cache_path(source_name)
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return None
    return text if text.endswith("\n") else text + "\n"


def write_cached_source_text(source_name: str, text: str) -> None:
    SOURCE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    source_cache_path(source_name).write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


def fetch_one_extra_source_text(source_name: str) -> tuple[str, str]:
    source = source_access_from_env(source_name)
    logging.info("Fetching extra source %s.", source.name)
    raw_text = fetch_text(
        source.url,
        login=source.login,
        password=source.password,
        extra_headers=source.headers,
        use_basic_auth=source.use_basic_auth,
        method=source.method,
        payload=source.payload,
    )
    text = extract_source_text(source, raw_text)
    if not looks_like_ads_txt(text):
        preview = " | ".join(line[:120] for line in text.splitlines()[:3])
        raise RuntimeError(f"{source.name} source does not look like app-ads.txt. First lines: {preview}")
    write_cached_source_text(source.name, text)
    return source.name.upper(), text


def fetch_extra_source_texts(source_names: Iterable[str]) -> list[tuple[str, str]]:
    extra_source_texts: list[tuple[str, str]] = []
    for source_name in source_names:
        source_key = source_name.strip().lower()
        try:
            source_label, text = fetch_one_extra_source_text(source_name)
            logging.info("%s extra source fetched: %s line(s).", source_key, len(text.splitlines()))
            extra_source_texts.append((source_label, text))
        except Exception as exc:
            cached_text = read_cached_source_text(source_key)
            if cached_text is None:
                raise RuntimeError(f"{source_key} source failed and no cached previous version is available.") from exc
            logging.warning(
                "%s source failed; using cached previous version with %s line(s). Error: %s",
                source_key,
                len(cached_text.splitlines()),
                exc,
            )
            extra_source_texts.append((source_key.upper(), cached_text))
    return extra_source_texts


def require_ftp_settings(settings: Settings) -> tuple[str, str, str]:
    missing = [
        name
        for name, value in (
            ("FTP_HOST", settings.ftp_host),
            ("FTP_USER", settings.ftp_user),
            ("FTP_PASSWORD", settings.ftp_password),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"Missing FTP secrets: {', '.join(missing)}")
    return settings.ftp_host or "", settings.ftp_user or "", settings.ftp_password or ""


def ftp_ensure_dir(ftp: ftplib.FTP, remote_dir: str) -> None:
    for part in [item for item in remote_dir.replace("\\", "/").split("/") if item]:
        try:
            ftp.cwd(part)
        except ftplib.error_perm:
            ftp.mkd(part)
            ftp.cwd(part)


def upload_to_ftp(settings: Settings, files: dict[str, bytes]) -> None:
    host, user, password = require_ftp_settings(settings)
    logging.info("Connecting to FTP %s:%s", host, settings.ftp_port)
    with ftplib.FTP() as ftp:
        ftp.connect(host, settings.ftp_port, timeout=30)
        ftp.login(user, password)
        ftp_ensure_dir(ftp, settings.ftp_remote_dir)
        for filename, payload in files.items():
            logging.info("Uploading %s (%s bytes)", filename, len(payload))
            ftp.storbinary(f"STOR {filename}", BytesReader(payload))


class BytesReader:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.offset = 0

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = len(self.payload) - self.offset
        chunk = self.payload[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk


def verify_urls(urls: Iterable[str], expected_text: str) -> None:
    expected_hash = hashlib.sha256(expected_text.encode("utf-8")).hexdigest()
    failures: list[str] = []
    for url in urls:
        logging.info("Verifying %s", url)
        success = False
        last_error = ""
        for attempt in range(1, 4):
            try:
                actual = fetch_text(f"{url}?_={int(time.time())}", timeout=30)
                actual_hash = hashlib.sha256(actual.encode("utf-8")).hexdigest()
                if actual_hash == expected_hash:
                    success = True
                    break
                last_error = "content hash does not match"
            except (HTTPError, URLError, TimeoutError) as exc:
                last_error = str(exc)
            logging.warning("Verification attempt %s failed for %s: %s", attempt, url, last_error)
            time.sleep(10)
        if not success:
            failures.append(f"{url}: {last_error}")
    if failures:
        raise RuntimeError("Verification failed: " + "; ".join(failures))


def wix_headers(settings: Settings, id_header: str, id_value: str) -> dict[str, str]:
    return {
        "Authorization": settings.wix_api_key or "",
        id_header: id_value,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "KidsGames-app-ads-updater/1.0",
    }


def wix_account_headers(settings: Settings) -> dict[str, str]:
    missing = [
        name
        for name, value in (
            ("WIX_API_KEY", settings.wix_api_key),
            ("WIX_ACCOUNT_ID", settings.wix_account_id),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"Missing Wix secrets: {', '.join(missing)}")

    return {
        "Authorization": settings.wix_api_key or "",
        "wix-account-id": settings.wix_account_id or "",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "KidsGames-app-ads-updater/1.0",
    }


def wix_identity_attempts(settings: Settings) -> list[tuple[str, str]]:
    missing = [
        name
        for name, value in (
            ("WIX_API_KEY", settings.wix_api_key),
            ("WIX_SITE_ID", settings.wix_site_id),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"Missing Wix secrets: {', '.join(missing)}")

    return [("wix-site-id", settings.wix_site_id or "")]


def wix_request(settings: Settings, method: str, payload: dict[str, object] | None = None) -> dict[str, object]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    errors: list[str] = []
    for id_header, id_value in wix_identity_attempts(settings):
        logging.info("Calling Wix API with %s", id_header)
        request = Request(WIX_ADS_TXT_URL, data=data, headers=wix_headers(settings, id_header, id_value), method=method)
        try:
            with urlopen(request, timeout=30) as response:
                body = response.read().decode("utf-8", errors="replace")
            return json.loads(body) if body else {}
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            errors.append(f"{id_header}: Wix error {exc.code}: {error_body[:500]}")
    raise RuntimeError("Wix API failed. " + " | ".join(errors))


def query_wix_sites(settings: Settings) -> dict[str, object]:
    payload = {"query": {"paging": {"limit": 100}}}
    data = json.dumps(payload).encode("utf-8")
    logging.info("Calling Wix Query Sites API with wix-account-id")
    request = Request(WIX_QUERY_SITES_URL, data=data, headers=wix_account_headers(settings), method="POST")
    try:
        with urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8", errors="replace")
        return json.loads(body) if body else {}
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Wix Query Sites error {exc.code}: {error_body[:500]}") from exc


def site_id_from_wix_site(site: object) -> str | None:
    if not isinstance(site, dict):
        return None
    value = site.get("id") or site.get("siteId")
    return value if isinstance(value, str) else None


def test_wix_site_access(settings: Settings) -> None:
    if not settings.wix_site_id:
        raise RuntimeError("Missing Wix secrets: WIX_SITE_ID")

    response = query_wix_sites(settings)
    sites = response.get("sites")
    if not isinstance(sites, list):
        raise RuntimeError(f"Wix Query Sites response does not contain sites list: {response}")

    site_ids = sorted(site_id for site_id in (site_id_from_wix_site(site) for site in sites) if site_id)
    logging.info("Wix Query Sites returned %s site(s).", len(site_ids))
    if settings.wix_site_id not in site_ids:
        visible = ", ".join(site_ids[:10]) if site_ids else "none"
        raise RuntimeError(f"WIX_SITE_ID is not visible to this API key/account. Visible site IDs: {visible}")
    logging.info("WIX_SITE_ID is visible to this API key/account.")


def extract_wix_content(response: dict[str, object]) -> str:
    content = response.get("content")
    if isinstance(content, str):
        return content

    ads_txt = response.get("adsTxt")
    if isinstance(ads_txt, dict):
        nested_content = ads_txt.get("content")
        if isinstance(nested_content, str):
            return nested_content

    raise RuntimeError(f"Wix response does not contain ads.txt content: {response}")


def get_wix_ads_txt(settings: Settings) -> str:
    logging.info("Reading Wix ads.txt via API")
    return extract_wix_content(wix_request(settings, "GET"))


def test_wix_read_write(settings: Settings) -> None:
    content = get_wix_ads_txt(settings)
    before_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    logging.info("Wix ads.txt read successfully (%s bytes).", len(content.encode("utf-8")))
    logging.info("Testing Wix ads.txt write permission by writing current content back.")
    wix_request(settings, "PUT", {"adsTxt": {"content": content}})
    actual = get_wix_ads_txt(settings)
    after_hash = hashlib.sha256(actual.encode("utf-8")).hexdigest()
    if after_hash != before_hash:
        raise RuntimeError("Wix write test failed: content changed after writing it back")
    logging.info("Wix ads.txt read/write test passed.")


def update_wix_ads_txt(settings: Settings, content: str) -> None:
    if not settings.wix_enabled:
        logging.warning("Wix update is disabled; set WIX_ENABLED=true after Wix API check passes.")
        return
    if not settings.wix_api_key and not settings.wix_site_id:
        logging.warning("Wix secrets are missing; Wix update skipped.")
        return
    logging.info("Updating Wix ads.txt via API")
    wix_request(settings, "PUT", {"adsTxt": {"content": content}})
    actual = get_wix_ads_txt(settings)
    if hashlib.sha256(actual.encode("utf-8")).hexdigest() != hashlib.sha256(content.encode("utf-8")).hexdigest():
        raise RuntimeError("Wix verification failed: content hash does not match")
    logging.info("Wix ads.txt verified via API.")


def send_telegram(settings: Settings, message: str) -> None:
    if not settings.notifications_enabled:
        logging.warning("Notifications are disabled; Telegram notification skipped.")
        return
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        logging.warning("Telegram secrets are missing; notification skipped.")
        return

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    body = (
        f"chat_id={url_quote(settings.telegram_chat_id)}&"
        f"text={url_quote(message)}&disable_web_page_preview=true"
    ).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            response.read()
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Telegram error {exc.code}: {error_body}") from exc
    logging.info("Telegram notification sent.")


def url_quote(value: str) -> str:
    from urllib.parse import quote_plus

    return quote_plus(value)


def run(settings: Settings, dry_run: bool = False, today_override: date | None = None) -> int:
    local_timezone = get_timezone(settings.timezone)
    today = today_override or datetime.now(local_timezone).date()
    logging.info("Starting KidsGames app-ads update check for %s", today.isoformat())
    if today_override:
        logging.warning("Test date override is enabled: %s", today.isoformat())

    source_text = fetch_text(settings.source_url)
    first_line = source_text.splitlines()[0] if source_text.splitlines() else ""
    logging.info("Source first line: %s", first_line)

    if not source_is_current(first_line, today):
        checked_at = datetime.now(local_timezone).strftime("%Y-%m-%d %H:%M")
        logging.info("%s checked", checked_at)
        return 0

    extra_source_texts = fetch_extra_source_texts(settings.extra_source_names)
    output_text = build_output(source_text, today, extra_source_texts)
    output_bytes = output_text.encode("utf-8")
    dated_filename = f"{today.isoformat()} KidsGames app-ads.txt"
    files = {
        "app-ads.txt": output_bytes,
        "ads.txt": output_bytes,
        dated_filename: output_bytes,
    }

    if dry_run:
        logging.info("Dry run enabled; FTP upload and verification skipped.")
        logging.info("Would upload: %s", ", ".join(files))
        return 0

    upload_to_ftp(settings, files)
    update_wix_ads_txt(settings, output_text)
    verify_urls(settings.verify_urls, output_text)
    updated_at = datetime.now(local_timezone).strftime("%Y-%m-%d %H:%M")
    logging.info("%s updated www.kidsgames.top\\app-ads.txt", updated_at)
    send_telegram(settings, TELEGRAM_SUCCESS_MESSAGE)
    logging.info("Update completed successfully.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Update KidsGames app-ads.txt files.")
    parser.add_argument("--dry-run", action="store_true", help="Build and check source without uploading.")
    parser.add_argument("--today", help="Override today's date for tests, format YYYY-MM-DD.")
    parser.add_argument("--test-telegram", action="store_true", help="Send only the Telegram test message.")
    parser.add_argument("--test-wix", action="store_true", help="Read Wix ads.txt through the API without updating.")
    parser.add_argument("--test-wix-write", action="store_true", help="Read Wix ads.txt, write the same content back, and verify.")
    parser.add_argument("--test-wix-sites", action="store_true", help="Check whether WIX_SITE_ID is visible to the Wix API key/account.")
    parser.add_argument("--test-source", help="Fetch one configured source without updating, for example: mintegral.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    args = parser.parse_args()

    setup_logging(args.verbose)
    try:
        if args.test_telegram:
            send_telegram(env_settings(), TELEGRAM_SUCCESS_MESSAGE)
            return 0
        if args.test_wix:
            content = get_wix_ads_txt(env_settings())
            logging.info("Wix ads.txt read successfully (%s bytes).", len(content.encode("utf-8")))
            return 0
        if args.test_wix_write:
            test_wix_read_write(env_settings())
            return 0
        if args.test_wix_sites:
            test_wix_site_access(env_settings())
            return 0
        if args.test_source:
            test_source_access(args.test_source)
            return 0
        today_override = date.fromisoformat(args.today) if args.today else None
        return run(env_settings(), dry_run=args.dry_run, today_override=today_override)
    except Exception:
        logging.exception("Update failed.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
