from __future__ import annotations

from job_radar.collect import collect_jobs
from job_radar.export import export_excel
from job_radar.notion_export import export_to_notion
from job_radar.score import score_jobs


def main() -> None:
    jobs = collect_jobs()
    scored_jobs = score_jobs()
    output_path = export_excel()
    notion_created, notion_duplicates, notion_eligible = export_to_notion()

    print(f"Collected {len(jobs)} job links")
    print(f"Scored {len(scored_jobs)} jobs")
    print(f"Created {output_path}")
    print(
        "Notion export: "
        f"{notion_created} created, {notion_duplicates} duplicates skipped, "
        f"{notion_eligible} eligible"
    )


if __name__ == "__main__":
    main()
