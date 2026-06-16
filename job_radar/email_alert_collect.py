from __future__ import annotations

import imaplib
import os
import re
from base64 import b64encode
from datetime import datetime, timedelta
from email import message_from_bytes
from email.header import decode_header
from email.message import Message
from email.policy import default
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse, urlunparse

from bs4 import BeautifulSoup
from bs4.element import Tag

from job_radar.collect import Source, clean_text, dedupe_jobs, make_job


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_NAME = "LinkedIn Job Alert Email"
SUBJECT_KEYWORDS = ("linkedin", "job alert", "jobs", "internship", "intern")
RECENT_DAYS = 7
DEFAULT_MAILBOX_CANDIDATES = ["INBOX", "Inbox", "\u6536\u4ef6\u7bb1"]

GENERIC_LINK_TEXT = {
    "apply",
    "apply now",
    "view job",
    "view jobs",
    "see job",
    "see jobs",
    "job",
    "jobs",
    "linkedin",
}


def mail_settings() -> tuple[str, int, list[str], str, str] | None:
    host = os.getenv("MAIL_IMAP_HOST", "imap.163.com").strip()
    port_text = os.getenv("MAIL_IMAP_PORT", "993").strip()
    mailbox_name = os.getenv("MAILBOX_NAME", "").strip()
    mailbox_candidates = [mailbox_name] if mailbox_name else DEFAULT_MAILBOX_CANDIDATES
    username = os.getenv("MAIL_USERNAME", "").strip()
    password = os.getenv("MAIL_PASSWORD", "").strip()

    if not username or not password:
        print("Warning: MAIL_USERNAME or MAIL_PASSWORD missing; skipping email alert collection.")
        return None

    try:
        port = int(port_text)
    except ValueError:
        print("Warning: MAIL_IMAP_PORT must be a number; skipping email alert collection.")
        return None

    return host, port, mailbox_candidates, username, password


def safe_decode(value: bytes | str) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def imap_status_ok(status: bytes | str) -> bool:
    return safe_decode(status).upper() == "OK"


def encode_modified_utf7(value: str) -> bytes:
    encoded_parts = []
    buffer = []

    def flush_buffer() -> None:
        if not buffer:
            return
        raw = "".join(buffer).encode("utf-16be")
        encoded = b64encode(raw).decode("ascii").rstrip("=").replace("/", ",")
        encoded_parts.append(f"&{encoded}-")
        buffer.clear()

    for char in value:
        ordinal = ord(char)
        if 0x20 <= ordinal <= 0x7E:
            flush_buffer()
            encoded_parts.append("&-" if char == "&" else char)
        else:
            buffer.append(char)

    flush_buffer()
    return "".join(encoded_parts).encode("ascii")


def mailbox_argument(candidate: str) -> str | bytes:
    try:
        candidate.encode("ascii")
        return candidate
    except UnicodeEncodeError:
        return encode_modified_utf7(candidate)


def print_available_mailboxes(mailbox: imaplib.IMAP4_SSL) -> None:
    status, data = mailbox.list()
    if status != "OK":
        print("Warning: could not list available IMAP mailboxes.")
        return

    names = [safe_decode(item) for item in data if item]
    if names:
        print("Available IMAP mailboxes:")
        for name in names:
            print(f"- {name}")
    else:
        print("Warning: IMAP mailbox list was empty.")


def select_mailbox(mailbox: imaplib.IMAP4_SSL, mailbox_candidates: list[str]) -> str | None:
    for candidate in mailbox_candidates:
        for readonly in (False, True):
            try:
                status, _data = mailbox.select(mailbox_argument(candidate), readonly=readonly)
            except imaplib.IMAP4.error:
                continue

            state = getattr(mailbox, "state", "")
            if imap_status_ok(status) and state == "SELECTED":
                print(f"Selected IMAP mailbox '{candidate}'.")
                return candidate

            if imap_status_ok(status):
                print(
                    "Warning: IMAP mailbox select returned OK for "
                    f"'{candidate}' but connection state is '{state}', not SELECTED."
                )

    print(
        "Warning: could not select any IMAP mailbox from candidates: "
        + ", ".join(mailbox_candidates)
    )
    print_available_mailboxes(mailbox)
    return None


def decode_subject(value: str | None) -> str:
    if not value:
        return ""

    parts = []
    for content, encoding in decode_header(value):
        if isinstance(content, bytes):
            parts.append(content.decode(encoding or "utf-8", errors="replace"))
        else:
            parts.append(content)
    return clean_text("".join(parts))


def subject_matches(subject: str) -> bool:
    lowered = subject.lower()
    return any(keyword in lowered for keyword in SUBJECT_KEYWORDS)


def message_date_is_recent(message: Message) -> bool:
    raw_date = message.get("Date")
    if not raw_date:
        return True
    try:
        from email.utils import parsedate_to_datetime

        message_date = parsedate_to_datetime(raw_date)
        if message_date.tzinfo:
            message_date = message_date.astimezone().replace(tzinfo=None)
        return message_date >= datetime.now() - timedelta(days=RECENT_DAYS + 1)
    except (TypeError, ValueError):
        return True


def decode_part_payload(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def message_bodies(message: Message) -> tuple[list[str], list[str]]:
    html_parts = []
    text_parts = []

    if message.is_multipart():
        for part in message.walk():
            if part.get_content_disposition() == "attachment":
                continue
            content_type = part.get_content_type()
            if content_type == "text/html":
                html_parts.append(decode_part_payload(part))
            elif content_type == "text/plain":
                text_parts.append(decode_part_payload(part))
    else:
        content_type = message.get_content_type()
        if content_type == "text/html":
            html_parts.append(decode_part_payload(message))
        elif content_type == "text/plain":
            text_parts.append(decode_part_payload(message))

    return html_parts, text_parts


def unwrap_tracking_url(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    for key in ("url", "u", "target", "redirect", "redirectUrl"):
        for value in query.get(key, []):
            decoded = unquote(value)
            if "linkedin.com" in decoded.lower():
                return decoded
    return url


def is_linkedin_job_url(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    query = parse_qs(parsed.query)

    if "linkedin.com" not in host:
        return False
    if "/jobs/view" in path or "/comm/jobs/view" in path:
        return True
    return "/jobs" in path and "currentJobId" in query


def normalize_linkedin_url(url: str) -> str:
    url = unwrap_tracking_url(url)
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    clean_query = ""
    if "currentJobId" in query and "/view" not in parsed.path.lower():
        clean_query = f"currentJobId={query['currentJobId'][0]}"

    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme, parsed.netloc.lower(), path, "", clean_query, ""))


def lines_from_text(text: str) -> list[str]:
    return [
        clean_text(line)
        for line in re.split(r"[\r\n]+", text)
        if clean_text(line)
    ]


def usable_title(text: str) -> bool:
    text = clean_text(text)
    return 4 <= len(text) <= 120 and text.lower() not in GENERIC_LINK_TEXT


def infer_company_location(lines: list[str], title: str) -> tuple[str, str]:
    clean_lines = [line for line in lines if line and line.lower() != title.lower()]
    clean_lines = [
        line
        for line in clean_lines
        if line.lower() not in GENERIC_LINK_TEXT and "linkedin" not in line.lower()
    ]
    company = clean_lines[0] if clean_lines else ""
    location = clean_lines[1] if len(clean_lines) > 1 else ""
    return company, location


def extract_from_html(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    source = Source(name=SOURCE_NAME, url="https://www.linkedin.com/jobs/")
    jobs = []

    for anchor in soup.find_all("a", href=True):
        if not isinstance(anchor, Tag):
            continue

        url = normalize_linkedin_url(str(anchor.get("href", "")))
        if not is_linkedin_job_url(url):
            continue

        title = clean_text(anchor.get_text(" ", strip=True))
        context = anchor
        for _ in range(3):
            if context.parent and isinstance(context.parent, Tag):
                context = context.parent

        context_lines = lines_from_text(context.get_text("\n", strip=True))
        if not usable_title(title):
            title = next((line for line in context_lines if usable_title(line)), "")

        company, location = infer_company_location(context_lines, title)
        job = make_job(title, company, location, source, url)
        if job:
            jobs.append(job)

    return jobs


def extract_urls_from_text(text: str) -> list[str]:
    return re.findall(r"https?://[^\s<>()\"']+", text)


def extract_from_plain_text(text: str) -> list[dict[str, str]]:
    source = Source(name=SOURCE_NAME, url="https://www.linkedin.com/jobs/")
    lines = lines_from_text(text)
    jobs = []

    for index, line in enumerate(lines):
        for raw_url in extract_urls_from_text(line):
            url = normalize_linkedin_url(raw_url.rstrip(".,;"))
            if not is_linkedin_job_url(url):
                continue

            nearby = lines[max(0, index - 4) : index + 2]
            title = next((item for item in reversed(nearby) if usable_title(item) and "http" not in item), "")
            company, location = infer_company_location(nearby, title)
            job = make_job(title, company, location, source, url)
            if job:
                jobs.append(job)

    return jobs


def extract_jobs_from_message(message: Message) -> list[dict[str, str]]:
    html_parts, text_parts = message_bodies(message)
    jobs = []
    for html in html_parts:
        jobs.extend(extract_from_html(html))
    for text in text_parts:
        jobs.extend(extract_from_plain_text(text))
    return dedupe_jobs(jobs)


def collect_email_alert_jobs() -> list[dict[str, str]]:
    settings = mail_settings()
    if settings is None:
        return []

    host, port, mailbox_candidates, username, password = settings
    since = (datetime.now() - timedelta(days=RECENT_DAYS)).strftime("%d-%b-%Y")
    collected = []

    try:
        with imaplib.IMAP4_SSL(host, port) as mailbox:
            mailbox.login(username, password)
            selected_mailbox = select_mailbox(mailbox, mailbox_candidates)
            if not selected_mailbox:
                return []
            if getattr(mailbox, "state", "") != "SELECTED":
                print("Warning: IMAP mailbox is not selected; skipping email alert collection.")
                return []

            status, data = mailbox.search(None, f'(SINCE "{since}")')
            if status != "OK":
                print("Warning: IMAP search failed; skipping email alert collection.")
                return []

            message_ids = data[0].split()
            for message_id in message_ids:
                status, fetched = mailbox.fetch(message_id, "(RFC822)")
                if status != "OK" or not fetched:
                    continue

                raw_message = fetched[0][1]
                message = message_from_bytes(raw_message, policy=default)
                subject = decode_subject(message.get("Subject"))
                if not subject_matches(subject) or not message_date_is_recent(message):
                    continue

                collected.extend(extract_jobs_from_message(message))
    except imaplib.IMAP4.error as exc:
        print(f"Warning: IMAP error; skipping email alert collection: {exc}")
        return []
    except OSError as exc:
        print(f"Warning: could not connect to IMAP mailbox; skipping email alert collection: {exc}")
        return []

    jobs = dedupe_jobs(collected)
    print(f"Collected {len(jobs)} LinkedIn job alert email jobs")
    return jobs


def main() -> None:
    jobs = collect_email_alert_jobs()
    print(f"Email alert collection returned {len(jobs)} jobs")


if __name__ == "__main__":
    main()
