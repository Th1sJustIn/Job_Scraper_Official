# Import Worker Documentation (`workers/import_companies.py`)

## 1. Purpose
The import worker ingests a CSV of companies and career page URLs, ensures company records exist, inserts career page records, and relies on DB triggers to enqueue initial scrape jobs.

---

## 2. File and Entry Point
- Worker file: `workers/import_companies.py`
- Main entry:
  - `python3 workers/import_companies.py <csv_path>`
  - defaults to `data/test_companies.csv` if no path is provided

Primary function:
- `import_companies(csv_file_path)`

---

## 3. Input Contract

Expected CSV headers:
- `company`
- `careers_url`

Behavior:
- Header names are normalized via `strip()`.
- Rows missing either value are skipped.
- File read uses `utf-8-sig` (handles BOM).

---

## 4. Database Interactions

Uses Supabase client from `database/client.py`.

For each row:
1. Check duplicate URL in `career_pages` by `url`.
2. Find company in `companies` by `name`.
3. Insert company if missing.
4. Insert career page row in `career_pages`.

Important side effect:
- `career_pages` insert trigger (`create_initial_scrape_job`) creates an initial `scrapes` row with `status='queued'`.

---

## 5. Operational Flow (Per Row)
1. Parse row.
2. Validate required fields.
3. Skip if URL already exists.
4. Resolve `company_id`:
   - existing company ID, or
   - newly inserted company ID.
5. Insert career page URL.
6. Update in-memory import stats.

Completion output:
- companies added
- URLs added
- duplicates skipped

---

## 6. Logging and Visibility

Current logs include:
- file read start
- duplicate URL skips
- company reused vs added
- URL insertion success/failure
- final summary metrics

No structured logging or persistence beyond stdout.

---

## 7. Error Handling

Handled cases:
- `FileNotFoundError` -> explicit message
- generic exceptions -> printed and function exits

Per-row resilience:
- insert failures print an error and continue to next row

Limitations:
- no retry/backoff for transient DB errors
- no dead-letter handling for bad rows

---

## 8. Data Integrity Guarantees

Guaranteed by code + schema:
- duplicate URLs are skipped pre-insert
- duplicate company names prevented by unique constraint
- duplicate `(company_id, url)` prevented in `career_pages`
- initial scrape job auto-created by trigger

Not guaranteed:
- URL normalization/canonicalization beyond exact string match
- strict URL validity checks at import stage

---

## 9. Failure Modes and Recovery

### 9.1 Bad/missing CSV
Symptoms:
- header error or file-not-found message

Recovery:
- fix CSV headers and path
- re-run import

### 9.2 Partial import due to transient DB issue
Symptoms:
- intermittent insert errors

Recovery:
- re-run import; duplicate safeguards prevent major duplication

### 9.3 Unexpected duplicate representations
Symptoms:
- semantically same URL with different formatting imports twice

Recovery:
- manual URL normalization policy update
- optional backfill dedupe job

---

## 10. Runbook

Typical commands:
- `python3 workers/import_companies.py data/test_companies.csv`
- `python3 workers/import_companies.py data/startup_sites.csv`

Pre-flight:
- confirm `.env` has Supabase credentials
- verify expected CSV headers

Post-run checks (manual):
- count newly created `career_pages`
- verify new `scrapes` rows with `status='queued'`

---

## 11. Extension Points

Common enhancements:
- strict URL validator at import time
- canonical URL normalization
- per-row error report export
- batching for large CSVs
- idempotent upsert semantics on URL

---

## 12. Related Docs
- `docs/SYSTEM_DOCUMENTATION.md`
- `docs/DATABASE_SYSTEM_DOCUMENTATION.md`
- `docs/WORKER_EXTRACT_SITE_CONTENT.md`
- `docs/HELPER_JOB_EXTRACTION.md`

