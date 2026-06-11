from __future__ import annotations

import csv
import re
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = PROJECT_ROOT / "config" / "profile.yaml"
INPUT_PATH = PROJECT_ROOT / "data" / "jobs_collected.csv"
OUTPUT_PATH = PROJECT_ROOT / "data" / "jobs_scored.csv"

OUTPUT_COLUMNS = [
    "date_found",
    "title",
    "company",
    "location",
    "source",
    "url",
    "score",
    "matched_keywords",
    "warning_keywords",
    "short_reason",
    "hard_filter_status",
    "hard_filter_reason",
    "hard_filter_category",
    "minimum_score_to_export",
]

CAREER_LEVEL_PATTERNS = (
    ("intern", r"\bintern\b"),
    ("internship", r"\binternship\b"),
    ("trainee", r"\btrainee\b"),
    ("graduate", r"\bgraduate\b"),
    ("entry level", r"\bentry[- ]level\b"),
    ("junior", r"\bjunior\b"),
    ("working student", r"\bworking\s+student\b"),
    ("student job", r"\bstudent\s+job\b"),
    ("early career", r"\bearly\s+career\b"),
    ("early careers", r"\bearly\s+careers\b"),
)

def load_profile(path: Path = PROFILE_PATH) -> dict:
    with path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def read_jobs(path: Path = INPUT_PATH) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def normalize_terms(terms: list[str]) -> list[str]:
    return [str(term).strip().lower() for term in terms if str(term).strip()]


def find_matches(text: str, terms: list[str]) -> list[str]:
    lowered = text.lower()
    return [term for term in terms if term in lowered]


def regex_matches(text: str, patterns: tuple[tuple[str, str], ...]) -> list[str]:
    matches = []
    for label, pattern in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            matches.append(label)
    return list(dict.fromkeys(matches))


def keyword_to_pattern(keyword: str) -> str:
    escaped = re.escape(keyword.strip())
    escaped = escaped.replace(r"\ ", r"[\s-]+")
    if keyword[:1].isalnum():
        escaped = r"\b" + escaped
    if keyword[-1:].isalnum():
        escaped = escaped + r"\b"
    return escaped


def flatten_negative_keywords(value: object, prefix: str = "negative_keywords") -> list[tuple[str, str]]:
    flattened = []
    if isinstance(value, dict):
        for key, nested_value in value.items():
            flattened.extend(flatten_negative_keywords(nested_value, f"{prefix}.{key}"))
    elif isinstance(value, list):
        for item in value:
            keyword = str(item).strip()
            if keyword:
                flattened.append((keyword, prefix))
    return flattened


def build_exclusion_patterns(profile: dict) -> list[tuple[str, str, str]]:
    patterns = []

    for keyword in normalize_terms(profile.get("warning_keywords", [])):
        patterns.append((keyword, "warning_keywords", keyword_to_pattern(keyword)))

    for keyword, category in flatten_negative_keywords(profile.get("negative_keywords", {})):
        normalized_keyword = keyword.lower()
        patterns.append((normalized_keyword, category, keyword_to_pattern(normalized_keyword)))

    deduped = {}
    for keyword, category, pattern in patterns:
        deduped.setdefault((keyword, category), pattern)
    return [(keyword, category, pattern) for (keyword, category), pattern in deduped.items()]


def find_exclusion_matches(text: str, patterns: list[tuple[str, str, str]]) -> list[tuple[str, str]]:
    matches = []
    for keyword, category, pattern in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            matches.append((keyword, category))
    return list(dict.fromkeys(matches))


def hard_filter_job(searchable_text: str, exclusion_patterns: list[tuple[str, str, str]]) -> tuple[str, str, str]:
    exclusion_matches = find_exclusion_matches(searchable_text, exclusion_patterns)
    if exclusion_matches:
        keywords = [keyword for keyword, _category in exclusion_matches]
        categories = [category for _keyword, category in exclusion_matches]
        return (
            "exclude",
            "matched exclusion keyword: " + ", ".join(keywords),
            ", ".join(dict.fromkeys(categories)),
        )

    career_matches = regex_matches(searchable_text, CAREER_LEVEL_PATTERNS)
    if career_matches:
        return "keep", "career-level keyword: " + ", ".join(career_matches), "career_level"

    return "exclude", "missing early-career keyword", "career_level"


def score_job(job: dict[str, str], profile: dict) -> dict[str, str]:
    scoring = profile.get("scoring", {})
    role_weight = int(scoring.get("role_match", 30))
    high_weight = int(scoring.get("high_priority_keyword", 8))
    medium_weight = int(scoring.get("medium_priority_keyword", 4))
    location_weight = int(scoring.get("location_match", 18))
    seniority_weight = int(scoring.get("good_seniority", 15))
    internship_weight = int(scoring.get("internship_fit", 10))
    warning_penalty = int(scoring.get("warning_keyword_penalty", 18))
    minimum_score_to_export = int(profile.get("minimum_score_to_export", 60))

    target_roles = normalize_terms(profile.get("target_roles", []))
    keyword_config = profile.get("target_keywords", {})
    high_keywords = normalize_terms(keyword_config.get("high_priority", []))
    medium_keywords = normalize_terms(keyword_config.get("medium_priority", []))
    target_locations = normalize_terms(profile.get("target_locations", []))
    good_seniority = normalize_terms(profile.get("good_seniority_keywords", []))
    warning_terms = normalize_terms(profile.get("warning_keywords", []))

    searchable_text = " ".join(
        [
            job.get("title", ""),
            job.get("company", ""),
            job.get("location", ""),
            job.get("source", ""),
            job.get("url", ""),
        ]
    )

    role_matches = find_matches(searchable_text, target_roles)
    high_matches = find_matches(searchable_text, high_keywords)
    medium_matches = find_matches(searchable_text, medium_keywords)
    location_matches = find_matches(searchable_text, target_locations)
    seniority_matches = find_matches(searchable_text, good_seniority)
    warnings = find_matches(searchable_text, warning_terms)
    exclusion_patterns = build_exclusion_patterns(profile)
    hard_filter_status, hard_filter_reason, hard_filter_category = hard_filter_job(
        searchable_text,
        exclusion_patterns,
    )

    score = 0
    score += role_weight if role_matches else 0
    score += high_weight * len(set(high_matches))
    score += medium_weight * len(set(medium_matches))
    score += location_weight if location_matches else 0
    score += seniority_weight if seniority_matches else 0

    internship_terms = {"intern", "internship", "trainee", "working student"}
    if internship_terms.intersection(set(seniority_matches + medium_matches + role_matches)):
        score += internship_weight

    score -= warning_penalty * len(set(warnings))
    score = max(score, 0)

    matched_keywords = sorted(set(role_matches + high_matches + medium_matches + location_matches + seniority_matches))
    reasons = []
    if role_matches:
        reasons.append("role fit")
    if high_matches:
        reasons.append("strong keyword match")
    if location_matches:
        reasons.append("target location")
    if seniority_matches:
        reasons.append("junior/internship fit")
    if warnings:
        reasons.append("seniority warning")
    if not reasons:
        reasons.append("weak text match; review manually")

    scored = dict(job)
    scored.update(
        {
            "score": str(score),
            "matched_keywords": ", ".join(matched_keywords),
            "warning_keywords": ", ".join(sorted(set(warnings))),
            "short_reason": "; ".join(reasons),
            "hard_filter_status": hard_filter_status,
            "hard_filter_reason": hard_filter_reason,
            "hard_filter_category": hard_filter_category,
            "minimum_score_to_export": str(minimum_score_to_export),
        }
    )
    return scored


def score_jobs() -> list[dict[str, str]]:
    profile = load_profile()
    jobs = read_jobs()
    scored_jobs = [score_job(job, profile) for job in jobs]
    scored_jobs.sort(key=lambda item: int(item.get("score", "0")), reverse=True)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(scored_jobs)

    return scored_jobs


def main() -> None:
    scored_jobs = score_jobs()
    print(f"Scored {len(scored_jobs)} jobs into {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
