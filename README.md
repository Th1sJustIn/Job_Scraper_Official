# Job Scraper Pipeline

## Project Description
This project ingests company career-page URLs, extracts page content, uses an LLM-assisted step to identify jobs, and stores normalized job records in Supabase.

Current milestone focus: **CS4265 Milestone 2 (M2) proof-of-concept**.
M2 goal is to prove viability of data acquisition, persistent storage, and pipeline structure.

## M2 Status (Current)
- Working acquisition path: **Yes** (authenticated Supabase access + retrievable sample records)
- Persistent storage path: **Yes** (`career_pages`, `scrapes`, `jobs` tables populated)
- Pipeline structure in repo: **Yes** (import, extraction, storage, orchestration scripts)
- Documentation baseline: **Updated for M2**

## Pipeline Components
- `import_companies.py`
  - Loads company + career-page URLs from CSV into Supabase.
- `extract_site_content.py`
  - Claims scrape jobs, fetches page HTML with Playwright, cleans/chunks content, updates `scrapes`.
- `job_extraction.py`
  - Claims cleaned scrapes, calls LLM extraction, normalizes jobs, upserts `jobs`.
- `extract_job_url_content.py`
  - Claims open jobs, fetches job URLs, stores page existence/content outcomes.
- `database/database.py`
  - Centralized database access and status transitions.

## Repository Structure
```text
project/
  src/                    
  database/
    AI_connection/
    client.py
    database.py
  docs/
  supabase/
    migrations/
  import_companies.py
  extract_site_content.py
  job_extraction.py
  extract_job_url_content.py
  requirements.txt
```

## Prerequisites
- Python 3.14+
- Playwright dependencies installed
- Supabase project URL + API key

## Setup
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

## Environment Variables
Create a local `.env` file using `.env.example`.

Required keys:
- `SUPABASE_PROJECT_URL`
- `SUPABASE_SECRET_KEY` or `SUPABASE_API_KEY`

Optional/secondary keys:
- `SUPABASE_DB_PASSWORD`
- `OLLAMA_URL`
- `GOOGLE_API_KEY`
- `GOOGLE_CSE_ID`

## Run Commands
Activate environment first:
```bash
source venv/bin/activate
```

Import companies:
```bash
python import_companies.py test_companies.csv
```

Run site-content worker:
```bash
python extract_site_content.py
```

Run core job extraction worker:
```bash
python job_extraction.py
```

Run job-url content worker:
```bash
python extract_job_url_content.py
```

## M2 Validation Commands
Syntax validation:
```bash
./venv/bin/python -m py_compile \
  import_companies.py \
  extract_site_content.py \
  job_extraction.py \
  extract_job_url_content.py \
  database/client.py \
  database/database.py \
  database/AI_connection/AI.py
```

Read-only Supabase persistence check:
```bash
./venv/bin/python - <<'PY'
from database.client import get_supabase_client
c=get_supabase_client()
for t in ['career_pages','scrapes','jobs']:
    r=c.table(t).select('id', count='exact').limit(1).execute()
    print(t, r.count)
PY
```

## Outputs / Storage
Primary persistent storage (Supabase):
- `career_pages`
- `scrapes`
- `jobs`
- `job_page_fetches`

## Security Notes
- Do not commit secrets/API keys.
- Keep `.env` local and use `.env.example` for required variable names.
- Ensure `.gitignore` excludes local credential files.

## M2 Deliverable Files
- M2 report source: `docs/M2_PROGRESS_REPORT.md`
- M2 report PDF: `CS4265_Justin_Marshall_M2.pdf`
- Evidence index: `docs/m2_evidence/README.md`
- Architecture update: `docs/ARCHITECTURE_M2.md`
