# job-radar

A minimal daily job-search workflow for collecting public job links, scoring them against your preferences, and exporting an Excel shortlist.

This first version:

- reads job preferences from `config/profile.yaml`
- reads public job board or company career URLs from `config/sources.yaml`
- collects likely job links from public pages
- scores jobs for role fit, keywords, location, seniority, and internship fit
- exports `daily_jobs.xlsx`

It does not scrape LinkedIn, does not auto-apply, and does not store passwords or personal information.

## Project Structure

```text
job-radar/
  config/
    profile.yaml        # Your role, keyword, location, and seniority preferences
    sources.yaml        # Public job board and company career page URLs
  data/
    .gitkeep
  job_radar/
    __init__.py
    collect.py          # Collect likely job links from public pages
    export.py           # Export scored jobs to Excel
    pipeline.py         # Run collect, score, and export together
    score.py            # Rank jobs against your profile
  requirements.txt
  README.md
```

## Setup

From this folder:

```powershell
cd C:\Users\xie4\Documents\autojobs\job-radar
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If PowerShell says `python` is not recognized, install Python 3.11 or newer first, then open a new PowerShell window and repeat the commands above.

## Add Sources

Edit `config/sources.yaml`.

Add public job boards or company career pages like this:

```yaml
sources:
  - name: Example Company
    type: company
    url: https://example.com/careers
    company: Example Company
    enabled: true
```

Avoid LinkedIn URLs for this version.

## Run Everything

```powershell
python -m job_radar.pipeline
```

This creates:

- `data/jobs_collected.csv`
- `data/jobs_scored.csv`
- `daily_jobs.xlsx`

## Run Individual Steps

Collect links:

```powershell
python -m job_radar.collect
```

Score collected jobs:

```powershell
python -m job_radar.score
```

Export Excel:

```powershell
python -m job_radar.export
```

## Excel Columns

The Excel file includes:

- `date_found`
- `title`
- `company`
- `location`
- `source`
- `url`
- `score`
- `matched_keywords`
- `warning_keywords`
- `short_reason`

## Notes

This collector is intentionally simple. Many modern career pages load jobs with JavaScript, and this version only reads links visible in the initial public HTML. If a source returns very few jobs, try adding a more direct jobs URL from that company or job board.
