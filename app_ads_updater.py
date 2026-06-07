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
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


SOURCE_URL = "https://raw.githubusercontent.com/cleveradssolutions/App-ads.txt/master/app-ads.txt"
DEFAULT_TIMEZONE = "Africa/Johannesburg"
DEFAULT_FTP_REMOTE_DIR = "tairgames.top"
LOG_PATH = Path("logs/app-ads-updater.log")
WIX_ADS_TXT_URL = "https://www.wixapis.com/promote-seo-robots-server/v2/ads"
WIX_QUERY_SITES_URL = "https://www.wixapis.com/site-list/v2/sites/query"
TELEGRAM_SUCCESS_MESSAGE = (
    "✅ Обновил ads файлы (с частью AZON)\n"
    "azon.games/app-ads.txt\n"
    "azon.games/ads.txt\n"
    "tairgames.top/app-ads.txt\n"
    "tairgames.top/ads.txt"
)

VERIFY_URLS = (
    "https://www.AZON.games/ads.txt",
    "https://www.AZON.games/app-ads.txt",
    "https://www.tairgames.top/ads.txt",
    "https://www.tairgames.top/app-ads.txt",
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
    "mintegral": "MINTEGRAL",
}

MINTEGRAL_MARKER = "Please replace your PublisherID with your actual publisher id acquired from Mintegral dashboard."
MINTEGRAL_PUBLISHER_ID = "47780"
MINTEGRAL_STOP_LINE = "aniview.com, 69d24331b4476e4a300e1584, RESELLER, 78b21b"
MINTEGRAL_MARKER_PATTERN = re.compile(
    r"please\s+replace\s+your\s+publisherid\s+with\s+your\s+actual\s+publisher\s+id\s+acquired\s+from\s+mintegral\s+dashboard\.?",
    re.IGNORECASE,
)
ADS_LINE_PATTERN = re.compile(
    r"([a-z0-9.-]+\.[a-z]{2,}\s*,\s*(?:your\s+PublisherID|[^,\s<]+)\s*,\s*(?:DIRECT|RESELLER)(?:\s*,\s*[^,\s<]+)?)",
    re.IGNORECASE,
)


AZON_LINES = (
    "# AZON Last updated {date_text}",
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
    verify_urls: tuple[str, ...]


@dataclass(frozen=True)
class SourceAccess:
    name: str
    url: str
    login: str | None
    password: str | None


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
        verify_urls=verify_urls,
    )


def fetch_text(
    url: str,
    timeout: int = 30,
    login: str | None = None,
    password: str | None = None,
) -> str:
    headers = {"User-Agent": "AZON-app-ads-updater/1.0"}
    if login and password:
        token = base64.b64encode(f"{login}:{password}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8-sig")


def source_access_from_env(source_name: str) -> SourceAccess:
    key = source_name.strip().lower()
    prefix = SOURCE_ENV_PREFIXES.get(key)
    if not prefix:
        known = ", ".join(sorted(SOURCE_ENV_PREFIXES))
        raise RuntimeError(f"Unknown source {source_name!r}. Known sources: {known}")

    url = os.getenv(f"{prefix}_SOURCE_URL")
    if not url:
        raise RuntimeError(f"Missing source secret: {prefix}_SOURCE_URL")

    return SourceAccess(
        name=key,
        url=url,
        login=os.getenv(f"{prefix}_LOGIN"),
        password=os.getenv(f"{prefix}_PASSWORD"),
    )


def looks_like_ads_txt(text: str) -> bool:
    stripped = text.lstrip()
    if stripped.lower().startswith(("<!doctype html", "<html")):
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
    return len(parts) >= 3 and parts[2].upper() in {"DIRECT", "RESELLER"}


def html_to_text(value: str) -> str:
    with_breaks = re.sub(r"(?i)<\s*br\s*/?\s*>", "\n", value)
    with_breaks = re.sub(r"(?i)</\s*(p|div|tr|li|pre|code|textarea)\s*>", "\n", with_breaks)
    without_tags = re.sub(r"<[^>]+>", "", with_breaks)
    return html.unescape(without_tags)


def replace_mintegral_publisher_id(line: str) -> str:
    return re.sub(r"your\s+PublisherID", MINTEGRAL_PUBLISHER_ID, line, flags=re.IGNORECASE)


def extract_mintegral_ads_txt(raw_text: str) -> str:
    text = html_to_text(raw_text) if raw_text.lstrip().lower().startswith(("<!doctype html", "<html")) else raw_text
    marker_match = MINTEGRAL_MARKER_PATTERN.search(text)
    regex_only = False
    if marker_match:
        after_marker = text[marker_match.end() :]
    else:
        normalized_text = " ".join(text.split())
        publisher_id_index = normalized_text.lower().find("your publisherid")
        if publisher_id_index < 0:
            preview_lines = [line.strip() for line in text.splitlines() if line.strip()][:10]
            preview = " | ".join(line[:160] for line in preview_lines)
            raise RuntimeError(f"Mintegral marker text was not found in source page. Text preview: {preview}")
        after_marker = normalized_text[max(0, publisher_id_index - 80) :]
        regex_only = True
    output_lines: list[str] = []
    stop_found = False

    if not regex_only:
        for raw_line in after_marker.splitlines():
            line = " ".join(raw_line.strip().split())
            if not line:
                continue
            line = replace_mintegral_publisher_id(line)
            if not is_ads_txt_line(line):
                continue
            output_lines.append(line)
            if line.startswith(MINTEGRAL_STOP_LINE):
                stop_found = True
                break

    if not stop_found:
        output_lines = []
        for match in ADS_LINE_PATTERN.finditer(after_marker):
            line = " ".join(match.group(1).strip().split())
            line = replace_mintegral_publisher_id(line)
            output_lines.append(line)
            if line.startswith(MINTEGRAL_STOP_LINE):
                stop_found = True
                break

    if not output_lines:
        raise RuntimeError("Mintegral ads block was found, but no app-ads.txt lines were extracted.")
    if not stop_found:
        raise RuntimeError(f"Mintegral stop line was not found: {MINTEGRAL_STOP_LINE}")

    return "\n".join(output_lines) + "\n"


def extract_source_text(source: SourceAccess, raw_text: str) -> str:
    if source.name == "mintegral":
        return extract_mintegral_ads_txt(raw_text)
    return raw_text


def test_source_access(source_name: str) -> None:
    source = source_access_from_env(source_name)
    auth_state = "with login/password" if source.login and source.password else "without auth"
    logging.info("Testing %s source access %s.", source.name, auth_state)
    raw_text = fetch_text(source.url, login=source.login, password=source.password)
    text = extract_source_text(source, raw_text)
    lines = text.splitlines()
    if not looks_like_ads_txt(text):
        preview = " | ".join(line[:120] for line in lines[:3])
        raise RuntimeError(f"{source.name} source does not look like app-ads.txt. First lines: {preview}")
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


def build_output(source_text: str, today: date) -> str:
    source_lines = source_text.splitlines()
    if len(source_lines) < 2:
        raise ValueError("Source app-ads.txt has fewer than two lines.")

    source_lines[1] = "OwnerDomain=AZON.games"
    azon_text = "\n".join(line.format(date_text=month_day_year(today)) for line in AZON_LINES)
    source_part = "\n".join(source_lines)
    return f"{azon_text}\n{source_part}\n"


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
        "User-Agent": "AZON-app-ads-updater/1.0",
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
        "User-Agent": "AZON-app-ads-updater/1.0",
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
    logging.info("Starting AZON app-ads update check for %s", today.isoformat())
    if today_override:
        logging.warning("Test date override is enabled: %s", today.isoformat())

    source_text = fetch_text(settings.source_url)
    first_line = source_text.splitlines()[0] if source_text.splitlines() else ""
    logging.info("Source first line: %s", first_line)

    if not source_is_current(first_line, today):
        checked_at = datetime.now(local_timezone).strftime("%Y-%m-%d %H:%M")
        logging.info("%s checked", checked_at)
        return 0

    output_text = build_output(source_text, today)
    output_bytes = output_text.encode("utf-8")
    dated_filename = f"{today.isoformat()} AZON app-ads.txt"
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
    logging.info("%s updated www.azon.games\\app-ads.txt (wix,tairgames.top)", updated_at)
    send_telegram(settings, TELEGRAM_SUCCESS_MESSAGE)
    logging.info("Update completed successfully.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Update AZON app-ads.txt files.")
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
