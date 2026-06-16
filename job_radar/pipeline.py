from __future__ import annotations

from job_radar.collect import collect_jobs, dedupe_jobs, write_jobs
from job_radar.email_alert_collect import collect_email_alert_jobs
from job_radar.export import export_excel, exportable_jobs
from job_radar.notion_export import export_to_notion
from job_radar.score import score_jobs


def main() -> None:
    public_jobs = collect_jobs()
    email_jobs = collect_email_alert_jobs()
    jobs = dedupe_jobs(public_jobs + email_jobs)
    write_jobs(jobs)

    scored_jobs = score_jobs()
    output_path = export_excel()
    excel_jobs = exportable_jobs(scored_jobs)
    notion_created, notion_duplicates, notion_eligible = export_to_notion()

    print(f"Collected {len(public_jobs)} public job links")
    print(f"Collected {len(email_jobs)} LinkedIn email alert job links")
    print(f"Merged {len(jobs)} total job links")
    print(f"Scored {len(scored_jobs)} jobs")
    print(f"Exported {len(excel_jobs)} jobs to Excel")
    print(f"Created {output_path}")
    print(
        "Notion export: "
        f"{notion_created} created, {notion_duplicates} duplicates skipped, "
        f"{notion_eligible} eligible"
    )


if __name__ == "__main__":
    main()
