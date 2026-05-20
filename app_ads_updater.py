from __future__ import annotations

import argparse
import ftplib
import hashlib
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

VERIFY_URLS = (
    "https://www.AZON.games/ads.txt",
    "https://www.AZON.games/app-ads.txt",
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


AZON_LINES = (
    "# AZON Updated {date_text} ",
    "google.com, pub-2206193735487862, DIRECT, f08c47fec0942fa0",
    "facebook.com, 982473989127847, DIRECT, c3e20eee3f780d68",
    "applovin.com, 3924b154e4c887949b692faf5649901d, DIRECT",
    "adcolony.com, 5d8cbf6671c93a42, RESELLER, 1ad675c9de6b5176",
    "rubiconproject.com, 16356, RESELLER, 0bfd66d529a55807",
    "openx.com, 540785403, RESELLER, 6a698e2ec38604c6",
    "indexexchange.com, 191086, RESELLER",
    "pubmatic.com, 158862, RESELLER, 5d62403b186f2ace",
    "pubnative.net, 1007170, RESELLER, d641df8625486a7b",
    "Verve.com, 15290, RESELLER, 0c8f5958fc2d6270",
    "indexexchange.com, 191086, RESELLER",
    "mangomob.net, 5000671859, DIRECT",
    "",
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
    verify_urls: tuple[str, ...]


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
        verify_urls=verify_urls,
    )


def fetch_text(url: str, timeout: int = 30) -> str:
    request = Request(url, headers={"User-Agent": "AZON-app-ads-updater/1.0"})
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8-sig")


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
    with urlopen(request, timeout=30) as response:
        response.read()
    logging.info("Telegram notification sent.")


def url_quote(value: str) -> str:
    from urllib.parse import quote_plus

    return quote_plus(value)


def run(settings: Settings, dry_run: bool = False) -> int:
    local_timezone = get_timezone(settings.timezone)
    today = datetime.now(local_timezone).date()
    logging.info("Starting AZON app-ads update check for %s", today.isoformat())

    source_text = fetch_text(settings.source_url)
    first_line = source_text.splitlines()[0] if source_text.splitlines() else ""
    logging.info("Source first line: %s", first_line)

    if not source_is_current(first_line, today):
        logging.info("%s checked", datetime.now(local_timezone).isoformat(timespec="seconds"))
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
    verify_urls(settings.verify_urls, output_text)
    send_telegram(settings, f"AZON app-ads.txt обновлен: {today.isoformat()}")
    logging.info("Update completed successfully.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Update AZON app-ads.txt files.")
    parser.add_argument("--dry-run", action="store_true", help="Build and check source without uploading.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    args = parser.parse_args()

    setup_logging(args.verbose)
    try:
        return run(env_settings(), dry_run=args.dry_run)
    except Exception:
        logging.exception("Update failed.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
