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
    notion_export.py    # Optionally export filtered jobs to Notion
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

`data/jobs_collected.csv` contains all collected jobs. `data/jobs_scored.csv` keeps all scored jobs and adds `hard_filter_status`, `hard_filter_reason`, `hard_filter_category`, and `minimum_score_to_export`. `daily_jobs.xlsx` only includes rows where `hard_filter_status` is `keep` and `score` is greater than `minimum_score_to_export`.

If Notion environment variables are configured, the pipeline also exports the same filtered jobs to Notion after creating the Excel file.

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

Export filtered jobs to Notion:

```powershell
python -m job_radar.notion_export
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

## Hard Filter

Before export, job-radar applies a hard filter for early-career suitability. A job is kept only when its available text includes an early-career signal such as `intern`, `internship`, `trainee`, `graduate`, `entry level`, `junior`, `working student`, `student job`, or `early career`.

All `warning_keywords` and all nested `negative_keywords` in `config/profile.yaml` are hard exclusion filters. This includes mismatch categories such as `role_mismatch` and `contract_mismatch`. If a job matches any exclusion keyword, it is excluded from `daily_jobs.xlsx` even when its score is high.

The Excel report also applies a score threshold. By default, only jobs with `score > 60` are exported. You can change this with `minimum_score_to_export` in `config/profile.yaml`.

## Notion Export

To export filtered jobs to Notion, create a Notion internal integration, share your job database with that integration, and set these environment variables:

```powershell
$env:NOTION_TOKEN="your_notion_integration_secret"
$env:NOTION_DATABASE_ID="your_database_id"
```

On GitHub Actions, add the same values as repository secrets named `NOTION_TOKEN` and `NOTION_DATABASE_ID`.

The Notion database should include these properties:

- `Job Title`
- `Company`
- `Location`
- `Source`
- `Score`
- `URL`
- `Date Found`
- `Status`
- `Short Reason`
- `Matched Keywords`

`Job Title` should be a title property. `Score` should be a number, `URL` should ideally be a URL property, and `Date Found` should ideally be a date property. `Status` can be a Status, Select, or text-style property. If `NOTION_TOKEN` or `NOTION_DATABASE_ID` is missing, job-radar prints a warning and skips Notion export instead of crashing.

## Notes

This collector is intentionally simple. Many modern career pages load jobs with JavaScript, and this version only reads links visible in the initial public HTML. If a source returns very few jobs, try adding a more direct jobs URL from that company or job board.
