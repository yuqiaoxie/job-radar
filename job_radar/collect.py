from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse, urlunparse

import requests
import yaml
from bs4 import BeautifulSoup
from bs4.element import Tag


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCES_PATH = PROJECT_ROOT / "config" / "sources.yaml"
OUTPUT_PATH = PROJECT_ROOT / "data" / "jobs_collected.csv"

JOB_HINTS = (
    "job",
    "jobs",
    "career",
    "careers",
    "position",
    "positions",
    "opening",
    "openings",
    "intern",
    "internship",
    "graduate",
    "trainee",
    "junior",
    "associate",
    "business",
    "growth",
    "marketing",
    "product",
    "strategy",
    "healthcare",
    "biotech",
    "medtech",
)

GENERIC_TITLE_BLOCKLIST = (
    "add salary",
    "companies hiring in germany",
    "deutsch",
    "english",
    "explore companies",
    "find a job",
    "for recruiters",
    "free job posting",
    "francais",
    "jobs by locations",
    "jobs netherlands",
    "learn more",
    "match me to jobs",
    "recruiter area",
    "salary estimator",
    "sign in",
    "vacancies",
)

IAMEXPAT_CATEGORIES = (
    "Supply Chain / Logistics",
    "Finance / Accounting",
    "Editing / Translation",
    "Marketing / PR",
    "IT & technology",
    "Customer service",
    "Engineering",
    "Sales",
    "Other",
)

OUTPUT_COLUMNS = [
    "date_found",
    "title",
    "company",
    "location",
    "source",
    "url",
]


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    source_type: str = "unknown"
    company: str = ""
    enabled: bool = True


def load_sources(path: Path = SOURCES_PATH) -> list[Source]:
    with path.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file) or {}

    sources = []
    for item in config.get("sources", []):
        if item.get("enabled", True):
            sources.append(
                Source(
                    name=str(item.get("name", "")).strip(),
                    url=str(item.get("url", "")).strip(),
                    source_type=str(item.get("type", "unknown")).strip(),
                    company=str(item.get("company", "") or "").strip(),
                    enabled=bool(item.get("enabled", True)),
                )
            )
    return [source for source in sources if source.name and source.url]


def fetch_html(url: str) -> str:
    headers = {
        "User-Agent": (
            "job-radar/0.1 local research tool "
            "(public pages only; no auto-apply)"
        )
    }
    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()
    return response.text


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme, parsed.netloc.lower(), path, "", "", ""))


def source_host(source: Source) -> str:
    return urlparse(source.url).netloc.lower()


def remove_posting_date_prefix(text: str) -> str:
    return clean_text(
        re.sub(
            r"^(?:featured\s+)?(?:(?:\d+\s+"
            r"(?:minute|hour|day|week|month|quarter|year)s?\s+ago)"
            r"|last\s+(?:week|month|quarter|year)|yesterday|today)\s+",
            "",
            text,
            flags=re.IGNORECASE,
        )
    )


def clean_title(raw_title: str) -> str:
    title = clean_text(raw_title)
    title = re.sub(r"\bFEATURED\b", "", title, flags=re.IGNORECASE)
    title = remove_posting_date_prefix(title)
    title = re.split(r"\s+Place of work\s*:", title, maxsplit=1, flags=re.IGNORECASE)[0]
    title = re.split(r"\s+Workload\s*:", title, maxsplit=1, flags=re.IGNORECASE)[0]
    title = re.split(r"\s+Contract type\s*:", title, maxsplit=1, flags=re.IGNORECASE)[0]
    title = re.split(r"\s+Posted date\s+", title, maxsplit=1, flags=re.IGNORECASE)[0]
    title = re.sub(r"\bPermanent position\b", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\bSalary Icon\b", "", title, flags=re.IGNORECASE)
    return clean_text(title.strip(" -|"))


def clean_location(raw_location: str) -> str:
    location = clean_text(raw_location)
    location = re.sub(r"\s+and\s+\d+\s+more$", "", location, flags=re.IGNORECASE)
    location = re.sub(r"\s+\d+-\d+\s+year.*$", "", location, flags=re.IGNORECASE)
    location = location.strip(" ,-")
    if not location or len(location) > 80:
        return ""
    if any(label in location.lower() for label in ("workload", "contract type", "posted date")):
        return ""
    return location


def clean_company(raw_company: str) -> str:
    company = clean_text(raw_company)
    company = re.split(r"\s+Posted date\s+", company, maxsplit=1, flags=re.IGNORECASE)[0]
    company = re.sub(r"\b(?:1mo|2mo|3mo|\d+d|\d+h)\b.*$", "", company, flags=re.IGNORECASE)
    company = company.strip(" ,-")
    if not company or len(company) > 80:
        return ""
    if any(label in company.lower() for label in ("place of work", "workload", "contract type")):
        return ""
    return company


def is_valid_title(title: str) -> bool:
    lowered = title.lower()
    if not title or len(title) < 4 or len(title) > 120:
        return False
    if lowered in GENERIC_TITLE_BLOCKLIST:
        return False
    if not re.search(r"[A-Za-z]", title):
        return False
    return True


def make_job(title: str, company: str, location: str, source: Source, url: str) -> dict[str, str] | None:
    title = clean_title(title)
    if not is_valid_title(title):
        return None
    cleaned_company = clean_company(company or source.company)
    cleaned_location = clean_location(location)
    if cleaned_company and cleaned_location.lower() == cleaned_company.lower():
        cleaned_location = ""

    return {
        "date_found": date.today().isoformat(),
        "title": title,
        "company": cleaned_company,
        "location": cleaned_location,
        "source": source.name,
        "url": normalize_url(url),
    }


def is_jobcloud_detail_url(url: str) -> bool:
    path = urlparse(url).path
    return "/vacancies/detail/" in path or "/jobs/detail/" in path


def parse_jobcloud_card_text(text: str) -> tuple[str, str, str]:
    text = remove_posting_date_prefix(text)
    parts = re.split(r"\bPlace of work\s*:\s*", text, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) == 1:
        return clean_title(text), "", ""

    title = clean_title(parts[0])
    after_place = parts[1]
    location = re.split(
        r"\s+(?:\d+-\d+\s+year|Workload\s*:|Contract type\s*:)",
        after_place,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]

    company = ""
    contract_match = re.search(
        r"Contract type\s*:\s*"
        r"(?:Permanent position|Internship|Temporary|Limited|Unlimited|Freelance|Apprenticeship)\s+(.+)$",
        after_place,
        flags=re.IGNORECASE,
    )
    if contract_match:
        company = contract_match.group(1)
    else:
        workload_match = re.search(
            r"Workload\s*:\s*[\d\s.%\u2013-]+(?:\s+(.+))?$",
            after_place,
            flags=re.IGNORECASE,
        )
        if workload_match:
            company = workload_match.group(1) or ""

    return title, company, location


def collect_jobcloud_jobs(source: Source, soup: BeautifulSoup) -> list[dict[str, str]]:
    jobs = []
    seen_urls = set()
    for anchor in soup.find_all("a", href=True):
        absolute_url = urljoin(source.url, str(anchor.get("href", "")).strip())
        if not is_jobcloud_detail_url(absolute_url):
            continue
        url_key = normalize_url(absolute_url)
        if url_key in seen_urls:
            continue

        title, company, location = parse_jobcloud_card_text(anchor.get_text(" ", strip=True))
        job = make_job(title, company, location, source, absolute_url)
        if job:
            seen_urls.add(url_key)
            jobs.append(job)
    return jobs


def is_arbeitnow_job_url(url: str) -> bool:
    path_parts = [part for part in urlparse(url).path.split("/") if part]
    if len(path_parts) != 4:
        return False
    if path_parts[:2] != ["jobs", "companies"]:
        return False
    return bool(re.search(r"-\d+$", path_parts[-1]))


def collect_arbeitnow_jobs(source: Source, soup: BeautifulSoup) -> list[dict[str, str]]:
    jobs = []
    seen_urls = set()
    for item in soup.find_all("li"):
        if not isinstance(item, Tag):
            continue
        title_link = item.select_one('[itemprop="title"] a[href]')
        if not title_link:
            continue

        absolute_url = urljoin(source.url, str(title_link.get("href", "")).strip())
        url_key = normalize_url(absolute_url)
        if url_key in seen_urls or not is_arbeitnow_job_url(absolute_url):
            continue

        company_node = item.select_one('[itemprop="hiringOrganization"]')
        location_node = item.select_one("span.text-gray-600")
        job = make_job(
            title_link.get_text(" ", strip=True),
            company_node.get_text(" ", strip=True) if company_node else "",
            location_node.get_text(" ", strip=True) if location_node else "",
            source,
            absolute_url,
        )
        if job:
            seen_urls.add(url_key)
            jobs.append(job)
    return jobs


def is_iamexpat_job_url(url: str) -> bool:
    path_parts = [part for part in urlparse(url).path.split("/") if part]
    return len(path_parts) >= 5 and path_parts[:2] == ["career", "jobs-netherlands"]


def parse_iamexpat_text(text: str) -> tuple[str, str]:
    text = clean_text(re.sub(r"\bFEATURED\b", "", text, flags=re.IGNORECASE))
    text = re.split(r"\s+Posted date\s+", text, maxsplit=1, flags=re.IGNORECASE)[0]
    for category in IAMEXPAT_CATEGORIES:
        marker = f" {category} "
        if marker.lower() in text.lower():
            index = text.lower().find(marker.lower())
            title = text[:index]
            location = text[index + len(marker) :]
            return title, location
    return text, ""


def collect_iamexpat_jobs(source: Source, soup: BeautifulSoup) -> list[dict[str, str]]:
    jobs = []
    seen_urls = set()
    for anchor in soup.find_all("a", href=True):
        absolute_url = urljoin(source.url, str(anchor.get("href", "")).strip())
        url_key = normalize_url(absolute_url)
        if url_key in seen_urls or not is_iamexpat_job_url(absolute_url):
            continue
        title, location = parse_iamexpat_text(anchor.get_text(" ", strip=True))
        job = make_job(title, "", location, source, absolute_url)
        if job:
            seen_urls.add(url_key)
            jobs.append(job)
    return jobs


def is_probable_generic_job_link(text: str, href: str) -> bool:
    combined = f"{text} {href}".lower()
    path = urlparse(href).path.lower()
    if href.startswith(("mailto:", "tel:", "javascript:")):
        return False
    if any(blocked in combined for blocked in ("linkedin.com", "/privacy", "/terms", "/signin", "/authenticate")):
        return False
    if not any(part in path for part in ("/job/", "/jobs/", "/career/", "/careers/", "/vacancies/")):
        return False
    return any(hint in combined for hint in JOB_HINTS)


def collect_generic_jobs(source: Source, soup: BeautifulSoup) -> list[dict[str, str]]:
    jobs = []
    seen_urls = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href", "")).strip()
        absolute_url = urljoin(source.url, href)
        anchor_text = clean_text(anchor.get_text(" ", strip=True))
        url_key = normalize_url(absolute_url)

        if url_key in seen_urls:
            continue
        if not is_probable_generic_job_link(anchor_text, absolute_url):
            continue

        job = make_job(anchor_text, source.company, "", source, absolute_url)
        if job:
            seen_urls.add(url_key)
            jobs.append(job)
    return jobs


def collect_from_source(source: Source) -> list[dict[str, str]]:
    html = fetch_html(source.url)
    soup = BeautifulSoup(html, "html.parser")
    host = source_host(source)

    if host.endswith(("jobs.ch", "jobup.ch")):
        return collect_jobcloud_jobs(source, soup)
    if host.endswith("arbeitnow.com"):
        return collect_arbeitnow_jobs(source, soup)
    if host.endswith("iamexpat.nl"):
        return collect_iamexpat_jobs(source, soup)
    return collect_generic_jobs(source, soup)


def job_quality(job: dict[str, str]) -> tuple[int, int]:
    filled_fields = sum(1 for key in ("company", "location") if job.get(key))
    title_length_score = max(0, 120 - len(job.get("title", "")))
    return filled_fields, title_length_score


def dedupe_jobs(jobs: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    by_url = {}
    for job in jobs:
        url_key = normalize_url(job.get("url", "").strip())
        if not url_key:
            continue
        existing = by_url.get(url_key)
        if not existing or job_quality(job) > job_quality(existing):
            by_url[url_key] = job

    by_title_company = {}
    for job in by_url.values():
        title_key = re.sub(r"[^a-z0-9]+", " ", job.get("title", "").lower()).strip()
        company_key = re.sub(r"[^a-z0-9]+", " ", job.get("company", "").lower()).strip()
        location_key = re.sub(r"[^a-z0-9]+", " ", job.get("location", "").lower()).strip()
        key = (title_key, company_key or location_key or job.get("source", ""))
        existing = by_title_company.get(key)
        if not existing or job_quality(job) > job_quality(existing):
            by_title_company[key] = job

    return list(by_title_company.values())


def write_jobs(jobs: list[dict[str, str]], path: Path = OUTPUT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(jobs)


def collect_jobs() -> list[dict[str, str]]:
    all_jobs = []
    for source in load_sources():
        try:
            all_jobs.extend(collect_from_source(source))
        except requests.RequestException as exc:
            print(f"Warning: could not read {source.name}: {exc}")

    jobs = dedupe_jobs(all_jobs)
    write_jobs(jobs)
    return jobs


def main() -> None:
    jobs = collect_jobs()
    print(f"Collected {len(jobs)} job links into {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
