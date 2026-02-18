# Job Scraper System Documentation

## 1. Purpose and Scope
This system ingests company career page URLs, scrapes and normalizes page content, uses an LLM to extract job listings, and stores those listings in Supabase with deduplication and status tracking.

Core goals:
- Track career pages and scraping attempts.
- Re-run scraping on a schedule-like recycle loop.
- Extract structured jobs from messy career page content.
- Upsert jobs by `(company_id, url)` to avoid duplicates.

---

## 2. High-Level Architecture

Main components:
- `import_companies.py`
- `extract_site_content.py`
- `job_extraction.py`
- `database/client.py`
- `database/database.py`
- `database/AI_connection/AI.py`
- Supabase migrations in `supabase/migrations/*.sql`

Conceptual pipeline:
1. Import companies and career page URLs.
2. DB trigger creates initial scrape job with status `queued`.
3. Content worker claims scrape jobs and sets status to `extracting`.
4. Content worker fetches page, cleans HTML, converts markdown, chunks text, sets status `cleaned` (or `core_extracted` when unchanged hash).
5. Core extraction worker claims `cleaned` jobs and sets status `core_extracting`.
6. Core extraction worker calls LLM per chunk, cleans/validates jobs, upserts into `jobs`, sets scrape status `core_extracted`.

---

## 3. Data Model

### 3.1 `companies`
Defined in: `supabase/migrations/20250131120000_create_companies.sql`

Fields:
- `id` BIGINT PK
- `name` TEXT UNIQUE NOT NULL

Use:
- Canonical company identity.

### 3.2 `career_pages`
Defined in: `supabase/migrations/20250131120500_create_career_pages.sql`

Fields:
- `id` BIGINT PK
- `company_id` FK -> `companies.id`
- `url` TEXT
- `last_hash` TEXT
- `last_updated` timestamptz
- `status` TEXT default `new`
- Unique constraint: `(company_id, url)`

Use:
- Source URLs to scrape.

### 3.3 `scrapes`
Defined in:
- `supabase/migrations/20250131121000_create_scrapes.sql`
- `supabase/migrations/20250201132500_add_company_name_to_scrapes.sql`
- `supabase/migrations/20260208120000_auto_create_scrape_job.sql`

Fields:
- `id` BIGINT PK
- `career_page_id` FK -> `career_pages.id`
- `raw_html` TEXT
- `markdown` TEXT
- `chunks_json` JSONB
- `chunk_count` INTEGER
- `html_hash` TEXT
- `status` TEXT
- `error_message` TEXT
- `company_name` TEXT (trigger-populated)
- `created_at` timestamptz

Use:
- Queue + state machine for scrape lifecycle.

### 3.4 `jobs`
Defined in: `supabase/migrations/20250201195600_create_jobs.sql`

Fields:
- `id` BIGINT PK
- `company_id` FK -> `companies.id`
- `title` TEXT NOT NULL
- `location` TEXT
- `department` TEXT
- `url` TEXT NOT NULL
- `first_seen_at` timestamptz default now
- `last_seen_at` timestamptz default now
- `status` TEXT default `open`
- `content_hash` TEXT
- `raw_scrape_id` BIGINT
- Unique constraint: `(company_id, url)`

Use:
- Durable record of extracted openings.

---

## 4. Worker Responsibilities

## 4.1 Import Worker (`import_companies.py`)

Responsibilities:
- Read CSV (`company`, `careers_url` columns).
- Create company if missing.
- Insert career page URL if missing.
- Skip duplicate URLs.

Important side effect:
- Inserting into `career_pages` triggers automatic creation of a `scrapes` row with status `queued`.

### 4.2 Site Content Worker (`extract_site_content.py`)

Responsibilities:
- Poll `fetch_next_scrape_job()` continuously.
- Claim one job atomically:
  - `queued -> extracting`
  - or recycle old `core_extracted` (>24h) -> `extracting`
- Navigate page with Playwright.
- Hash content and compare with latest hash.
- If unchanged hash: set status to `core_extracted` and skip heavy processing.
- Else clean HTML, convert markdown, normalize, chunk, and persist:
  - update scrape row with `raw_html`, `markdown`, `chunks_json`, `chunk_count`, `html_hash`
  - set status to `cleaned`
- On processing failure: set status `failed` and write `error_message`.

### 4.3 Core Extraction Worker (`job_extraction.py`)

Responsibilities:
- Poll `fetch_next_ready_job()` continuously.
- Claim one cleaned scrape atomically:
  - `cleaned -> core_extracting`
- For each markdown chunk:
  - call `extract_jobs_from_chunk()` in `database/AI_connection/AI.py`
- Normalize and validate extracted jobs:
  - unwrap markdown links
  - normalize relative URLs against career page URL
  - filter invalid URLs
  - dedupe within current batch
  - normalize title/location/department
- Upsert valid jobs into `jobs` with conflict target `(company_id, url)`.
- On success: set scrape status to `core_extracted`.
- On exception: set scrape status to `failed` and set `error_message`.

---

## 5. Status Lifecycle and Cross-Worker Transitions

This is the core operational state machine on `scrapes.status`.

### 5.1 Status Values in Use
- `queued`
- `extracting`
- `cleaned`
- `core_extracting`
- `core_extracted`
- `failed`

Legacy/default note:
- Migration default for `scrapes.status` is `fetched`, but normal runtime flow uses values above.

### 5.2 Transition Matrix

1. `career_pages` insert trigger
- Trigger function `create_initial_scrape_job()`
- Transition: `none -> queued`

2. Site content worker lock
- Function: `fetch_next_scrape_job()`
- Transition: `queued -> extracting`

3. Site content worker recycle flow
- Function: `fetch_next_scrape_job()`
- Condition: `core_extracted` scrape older than 24h
- Transition: `core_extracted -> extracting` (also resets `created_at`)

4. Site content worker success
- Function: `update_scrape_job()`
- Transition: `extracting -> cleaned`

5. Site content worker hash unchanged short-circuit
- Function: `update_scrape_status(..., "core_extracted")`
- Transition: `extracting -> core_extracted`

6. Site content worker failure
- Function: `fail_scrape_job()`
- Transition: `extracting -> failed`

7. Core extraction worker lock
- Function: `fetch_next_ready_job()`
- Transition: `cleaned -> core_extracting`

8. Core extraction worker success
- Function: `update_scrape_status(..., "core_extracted")`
- Transition: `core_extracting -> core_extracted`

9. Core extraction worker failure
- Function: `fail_scrape_job()`
- Transition: `core_extracting -> failed`

### 5.3 End-to-End Happy Path
`queued -> extracting -> cleaned -> core_extracting -> core_extracted`

### 5.4 Common Alternate Path (No Content Change)
`core_extracted (old) -> extracting -> core_extracted`

### 5.5 Failure Paths
- Content stage failure:
  - `queued -> extracting -> failed`
- Core extraction stage failure:
  - `queued -> extracting -> cleaned -> core_extracting -> failed`

---

## 6. AI Extraction Layer

File: `database/AI_connection/AI.py`

Current behavior:
- Sends each chunk to Ollama-compatible endpoint:
  - `MODEL = "qwen2.5:3b"`
  - `OLLAMA_URL = " http://192.168.1.248:11434/api/chat"`
- Retries up to 2 attempts.
- Parses `res.json()["message"]["content"]` as JSON after markdown/control-char cleanup.
- If all attempts fail, returns `[]`.

Prompt contract:
- File: `database/AI_connection/prompts.py`
- Strict JSON array of objects:
  - `department`, `title`, `location`, `job_url`
- Explicitly excludes category/filter/nav links.

Operational implication:
- Returning `[]` on repeated connection failures can make extraction appear successful if no exception is raised at worker level.

---

## 7. Deduplication and Data Quality Rules

Applied in `job_extraction.py`:
- Job uniqueness for DB writes:
  - `jobs` upsert conflict key `(company_id, url)`
- Batch-level dedupe:
  - in-memory `seen` set on `(company_id, job_url)`
- URL handling:
  - unwrap markdown links `[text](url)`
  - allow absolute or safe relative patterns
  - resolve relative URLs against career page base URL
- Title cleaning:
  - strip markdown links
  - normalize wrappers and whitespace

---

## 8. Runtime and Setup

Dependencies (from `requirements.txt`):
- `playwright`
- `beautifulsoup4`
- `markdownify`
- `python-dotenv`
- `supabase`
- `ollama`
- `lxml`

Environment variables (required by `database/client.py`):
- `SUPABASE_PROJECT_URL`
- `SUPABASE_SECRET_KEY` or `SUPABASE_API_KEY`

Typical run sequence:
1. Import source companies:
   - `python3 import_companies.py test_companies.csv`
2. Start content worker:
   - `python3 extract_site_content.py`
3. Start core extraction worker:
   - `python3 job_extraction.py`

Recommended deployment model:
- Run workers as independent long-running processes.
- Use separate supervision for each process (systemd, docker restart policies, PM2 equivalent, etc.).

---

## 9. Failure Modes and Recovery

### 9.1 Playwright/browser failures
Symptoms:
- `extracting` jobs become `failed` with navigation/runtime errors.

Recovery:
- Validate Playwright install and browser binaries.
- Requeue failed scrape by setting status back to `queued` manually.

### 9.2 Supabase credential/config errors
Symptoms:
- startup error from `get_supabase_client()`.

Recovery:
- Check `.env` values for project URL and key.

### 9.3 LLM endpoint unavailable or malformed responses
Symptoms:
- repeated AI extraction logs and empty extraction results.

Recovery:
- Validate `OLLAMA_URL`, model availability, and network reachability.
- Consider changing AI error handling to raise on connection failure when stage-level failure visibility is required.

### 9.4 Stuck queues or no processing
Symptoms:
- workers run but no transitions.

Recovery:
- Verify active statuses in `scrapes`.
- Confirm there are `queued` or `cleaned` rows.
- Check if rows are stranded in `extracting`/`core_extracting` from interrupted workers and reset intentionally.

---

## 10. Extension Guide

### 10.1 Add new extracted job field
1. Add column migration for `jobs`.
2. Update prompt schema in `database/AI_connection/prompts.py`.
3. Update cleanup and mapping logic in `job_extraction.py`.
4. Verify upsert payload includes new field.

### 10.2 Add new scrape status
1. Define intended transition and owner worker.
2. Update lock/query functions in `database/database.py`.
3. Update both workers to respect the new state.
4. Update this documentation status matrix.

### 10.3 Tune chunking/throughput
- `chunk_text(size=3000, overlap=400)` in `extract_site_content.py`
- Poll intervals:
  - content worker sleep: 7s
  - core extraction worker sleep: 5s

---

## 11. File Map

- Import pipeline: `import_companies.py`
- Content extraction worker: `extract_site_content.py`
- Core/LLM extraction worker: `job_extraction.py`
- DB client/env loading: `database/client.py`
- DB operations + queue locking: `database/database.py`
- LLM request layer: `database/AI_connection/AI.py`
- Prompt contract: `database/AI_connection/prompts.py`
- Schema and triggers: `supabase/migrations/*.sql`

