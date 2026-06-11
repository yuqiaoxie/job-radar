from __future__ import annotations

from job_radar.collect import collect_jobs
from job_radar.export import export_excel
from job_radar.score import score_jobs


def main() -> None:
    jobs = collect_jobs()
    scored_jobs = score_jobs()
    output_path = export_excel()

    print(f"Collected {len(jobs)} job links")
    print(f"Scored {len(scored_jobs)} jobs")
    print(f"Created {output_path}")


if __name__ == "__main__":
    main()

