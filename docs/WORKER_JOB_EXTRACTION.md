# Core Extraction Worker Documentation (`job_extraction.py`)

## 1. Purpose
This worker consumes cleaned scrape content, calls the AI extraction layer per chunk, validates and normalizes extracted jobs, and upserts job records into `jobs`.

---

## 2. File and Entry Point
- Worker file: `job_extraction.py`
- Main entry:
  - `python3 job_extraction.py`
- Loop runner:
  - `extract_jobs()`
- Single scrape processor:
  - `process_scrape(scrape)`

---

## 3. Queue and Locking Model

Queue source:
- `scrapes` rows with `status='cleaned'`

Claim function:
- `fetch_next_ready_job()` in `database/database.py`

Atomic claim behavior:
- read candidate with status `cleaned`
- conditional update `status='core_extracting'` with status guard
- return candidate only when update succeeds

Effect:
- optimistic locking prevents concurrent claim collisions.

---

## 4. Processing Pipeline

For each claimed scrape:
1. Read `chunks_json`, `chunk_count`, and nested `career_pages(company_id, url)`.
2. Validate `company_id` exists.
3. For each chunk:
   - call `extract_jobs_from_chunk(chunk)` from `database/AI_connection/AI.py`
   - append returned listings.
4. Run `clean_jobs(...)` normalization/validation pass.
5. Upsert cleaned jobs into `jobs` using conflict key `(company_id, url)`.
6. Set scrape status to `core_extracted` on success.

If any exception escapes processing:
- set scrape status to `core_extraction_failed`
- persist `error_message`

---

## 5. AI Layer Contract (Current)

Called module:
- `database/AI_connection/AI.py`

Current behavior:
- attempts LLM call up to 2 times
- returns parsed JSON array when successful
- if all attempts fail or parsing keeps failing, currently returns `[]`

Operational impact:
- connection failures can look like empty extraction instead of hard failure when no exception is raised.

---

## 6. Data Cleaning and Validation Rules

Implemented in `clean_jobs(...)` and helpers.

### 6.1 URL Rules
- unwrapped markdown URL support:
  - `[text](url)` -> `url`
- accepts:
  - absolute URLs (`http...`)
  - root-relative URLs (`/...`)
  - selected non-root relative prefixes:
    - `/`, `?`, `job`, `jobs`, `opening`, `openings`
- resolves relative URLs against career page base URL
- rejects URLs with spaces or invalid patterns

### 6.2 Title Rules
- removes markdown-link wrappers from titles
- normalizes whitespace
- strips full-string outer `[]` or `()` wrappers

### 6.3 Field Normalization
- `location` and `department` lists are joined into comma-separated strings
- empty/missing fields become empty strings during final payload construction

### 6.4 Dedupe Rules
- in-batch dedupe key: `(company_id, job_url)`
- persistent dedupe/upsert key: `(company_id, url)` in DB

---

## 7. Jobs Upsert Semantics

DB function:
- `insert_jobs(jobs_data)` in `database/database.py`

Behavior:
- `upsert(..., on_conflict="company_id, url")`
- updates existing records when URL already exists for same company

Fields written per job:
- `company_id`
- `title`
- `location`
- `department`
- `url`
- `content_hash` (MD5 of title+url)
- `raw_scrape_id`
- `status='open'`
- `last_seen_at`

---

## 8. Status Transitions Owned by This Worker

Input status consumed:
- `cleaned`

Transitions:
1. `cleaned -> core_extracting` (claim lock)
2. `core_extracting -> core_extracted` (success)
3. `core_extracting -> core_extraction_failed` (error path)

Downstream meaning:
- `core_extracted` marks scrape as fully processed for current cycle.

---

## 9. Error Handling

Worker loop:
- outer `try/except` prevents hard crash, sleeps 5s on global failure

Per-scrape:
- inner `try/except` around `process_scrape`
- on exception:
  - log error
  - `fail_scrape_job(scrape_id, error, status="core_extraction_failed")`

LLM connectivity preflight:
- before chunk extraction, worker checks LLM server with `GET /api/tags`
- endpoint is derived from `OLLAMA_URL` host/port
- if connectivity check fails:
  - scrape is marked `core_extraction_failed`
  - worker sleeps 60 seconds before next run

Granularity limitations:
- no explicit dead-letter queue

---

## 10. Observability

Current logs include:
- scrape ID and company ID
- chunk progress
- raw/cleaned job counts
- inserted/upserted estimates
- status updates

No structured logs or metrics currently.

---

## 11. Failure Modes and Recovery

### 11.1 AI endpoint unavailable
Symptoms:
- repeated AI error logs
- possible low/zero extraction counts

Recovery:
- verify AI host/model availability
- if needed, change AI layer to raise connection errors so scrape is marked failed

### 11.2 Invalid AI JSON payloads
Symptoms:
- parse errors in AI layer

Recovery:
- tighten prompt output constraints
- improve cleanup logic
- add stricter schema validation

### 11.3 Missing career page URL/company mapping
Symptoms:
- exceptions for missing required metadata

Recovery:
- repair relational integrity in source tables
- rerun affected scrapes

---

## 12. Runtime Notes

Poll interval:
- 5 seconds when no job is available

Scale pattern:
- can run multiple instances because claims are optimistic-lock protected

Primary bottleneck:
- LLM response latency per chunk

---

## 13. Extension Points

High-value improvements:
- stage-specific failure status (e.g., `core_extraction_failed`)
- explicit AI transport timeout/retry strategy
- schema-level validation for AI result shape
- close stale jobs based on `last_seen_at` policies

---

## 14. Related Docs
- `docs/SYSTEM_DOCUMENTATION.md`
- `docs/DATABASE_SYSTEM_DOCUMENTATION.md`
- `docs/WORKER_IMPORT_COMPANIES.md`
- `docs/WORKER_EXTRACT_SITE_CONTENT.md`
