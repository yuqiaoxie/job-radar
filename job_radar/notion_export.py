from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Any

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INPUT_PATH = PROJECT_ROOT / "data" / "jobs_scored.csv"
NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

PROPERTY_MAPPING = {
    "Job Title": "title",
    "Company": "company",
    "Location": "location",
    "Source": "source",
    "Score": "score",
    "URL": "url",
    "Date Found": "date_found",
    "Status": "status",
    "Short Reason": "short_reason",
    "Matched Keywords": "matched_keywords",
}


def read_scored_jobs(path: Path = INPUT_PATH) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def should_export(job: dict[str, str]) -> bool:
    try:
        score = int(job.get("score", "0"))
        minimum_score = int(job.get("minimum_score_to_export", "60"))
    except ValueError:
        return False
    return job.get("hard_filter_status", "").strip().lower() == "keep" and score > minimum_score


def notion_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def request_notion(
    method: str,
    endpoint: str,
    token: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = requests.request(
        method,
        f"{NOTION_API_BASE}{endpoint}",
        headers=notion_headers(token),
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def get_database_properties(token: str, database_id: str) -> dict[str, dict[str, Any]]:
    database = request_notion("GET", f"/databases/{database_id}", token)
    return database.get("properties", {})


def text_content(value: str, limit: int = 1900) -> list[dict[str, dict[str, str]]]:
    value = str(value or "").strip()
    if not value:
        return []
    return [{"text": {"content": value[:limit]}}]


def select_options(value: str) -> list[dict[str, str]]:
    return [{"name": item.strip()} for item in value.split(",") if item.strip()]


def property_value(prop_type: str, value: str) -> dict[str, Any] | None:
    value = str(value or "").strip()

    if prop_type == "title":
        return {"title": text_content(value)}
    if prop_type == "rich_text":
        return {"rich_text": text_content(value)}
    if prop_type == "url":
        return {"url": value or None}
    if prop_type == "number":
        try:
            return {"number": int(value)}
        except ValueError:
            return {"number": None}
    if prop_type == "date":
        return {"date": {"start": value} if value else None}
    if prop_type == "status":
        return {"status": {"name": value}} if value else None
    if prop_type == "select":
        return {"select": {"name": value}} if value else None
    if prop_type == "multi_select":
        return {"multi_select": select_options(value)}
    return None


def build_page_properties(
    job: dict[str, str],
    database_properties: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    properties = {}
    for notion_name, job_key in PROPERTY_MAPPING.items():
        if notion_name not in database_properties:
            continue

        value = "New" if notion_name == "Status" else job.get(job_key, "")
        prop_type = database_properties[notion_name].get("type", "")
        notion_value = property_value(prop_type, value)
        if notion_value is not None:
            properties[notion_name] = notion_value

    return properties


def duplicate_filter_payload(url: str, url_property_type: str) -> dict[str, Any] | None:
    if url_property_type == "url":
        return {"property": "URL", "url": {"equals": url}}
    if url_property_type == "rich_text":
        return {"property": "URL", "rich_text": {"equals": url}}
    if url_property_type == "title":
        return {"property": "URL", "title": {"equals": url}}
    return None


def url_exists(
    token: str,
    database_id: str,
    database_properties: dict[str, dict[str, Any]],
    url: str,
) -> bool:
    url_property = database_properties.get("URL")
    if not url_property:
        print("Warning: Notion database has no URL property; duplicate check skipped.")
        return False

    filter_payload = duplicate_filter_payload(url, url_property.get("type", ""))
    if not filter_payload:
        print("Warning: Notion URL property is not url/rich_text/title; duplicate check skipped.")
        return False

    payload = {"filter": filter_payload, "page_size": 1}
    result = request_notion("POST", f"/databases/{database_id}/query", token, payload)
    return bool(result.get("results"))


def create_page(
    token: str,
    database_id: str,
    database_properties: dict[str, dict[str, Any]],
    job: dict[str, str],
) -> None:
    properties = build_page_properties(job, database_properties)
    if "Job Title" not in properties:
        raise ValueError("Notion database must include a Job Title title property.")

    payload = {
        "parent": {"database_id": database_id},
        "properties": properties,
    }
    request_notion("POST", "/pages", token, payload)


def export_to_notion() -> tuple[int, int, int]:
    token = os.getenv("NOTION_TOKEN", "").strip()
    database_id = os.getenv("NOTION_DATABASE_ID", "").strip()
    if not token or not database_id:
        print("Warning: NOTION_TOKEN or NOTION_DATABASE_ID missing; skipping Notion export.")
        return 0, 0, 0

    jobs = [job for job in read_scored_jobs() if should_export(job)]
    if not jobs:
        print("No filtered jobs to export to Notion.")
        return 0, 0, 0

    try:
        database_properties = get_database_properties(token, database_id)
    except requests.RequestException as exc:
        print(f"Warning: could not read Notion database; skipping Notion export: {exc}")
        return 0, 0, len(jobs)

    created = 0
    skipped_duplicates = 0

    for job in jobs:
        url = job.get("url", "").strip()
        try:
            if url and url_exists(token, database_id, database_properties, url):
                skipped_duplicates += 1
                continue
            create_page(token, database_id, database_properties, job)
            created += 1
        except (requests.RequestException, ValueError) as exc:
            title = job.get("title", "Untitled job")
            print(f"Warning: could not export '{title}' to Notion: {exc}")

    print(
        "Notion export complete: "
        f"{created} created, {skipped_duplicates} duplicates skipped, {len(jobs)} eligible."
    )
    return created, skipped_duplicates, len(jobs)


def main() -> None:
    export_to_notion()


if __name__ == "__main__":
    main()
