# Site Content Worker Documentation (`extract_site_content.py`)

## 1. Purpose
This worker fetches raw career page content, cleans and normalizes it, chunks text for downstream AI extraction, and manages scrape queue progression from `queued`/recycled to `cleaned` (or `core_extracted` on unchanged content).

---

## 2. File and Entry Point
- Worker file: `extract_site_content.py`
- Main entry:
  - `python3 extract_site_content.py`
- Loop runner:
  - `run_worker()`
- Single-job processor:
  - `process_scrape_job(scrape_job)`

---

## 3. Queue and Locking Model

Queue source:
- `scrapes` table

Job claim function:
- `fetch_next_scrape_job()` in `database/database.py`

Claim rules:
1. Prefer one row where `status='queued'`.
2. If none found, pick one row where:
   - `status='core_extracted'`
   - `created_at < now - 24h`
3. Atomic lock update:
   - sets `status='extracting'`
   - resets `created_at` to current UTC
   - guarded by `.eq("status", original_status)` optimistic lock condition

Result:
- prevents multiple workers from claiming same row simultaneously.

---

## 4. Processing Pipeline

For each claimed job:
1. Resolve `career_page_id` -> URL via `get_career_page_url`.
2. Open Playwright Chromium (headless).
3. Navigate to URL and wait for network idle.
4. Sleep 5 seconds (extra page stabilization).
5. Read full page HTML.
6. Compute `html_hash` (MD5).
7. Compare with latest hash from `get_latest_scrape_hash`.
8. If hash unchanged:
   - set `scrapes.status='core_extracted'`
   - skip markdown/chunk generation.
9. If hash changed:
   - clean HTML (`clean_html`)
   - convert to markdown (`markdownify`)
   - normalize text (`normalize`)
   - chunk text (`chunk_text`, defaults `size=3000`, `overlap=400`)
   - persist via `update_scrape_job()` which sets `status='cleaned'`.

---

## 5. Core Functions

### `clean_html(html)`
- Parses HTML with BeautifulSoup/lxml.
- Removes noise tags:
  - `script`, `style`, `noscript`, `svg`, `canvas`, `iframe`, `header`, `footer`, `nav`

### `remove_artifacts(text)` + `normalize(text)`
- Removes long symbol runs and excessive blank lines.
- Collapses whitespace.

### `chunk_text(text, size=3000, overlap=400)`
- Produces overlapping chunks for AI extraction.
- Includes guard against invalid overlap loops.

---

## 6. Status Transitions Owned by This Worker

Input statuses consumed:
- `queued`
- `core_extracted` (older than 24h recycle path)

Transitions:
1. `queued -> extracting` (claim)
2. `core_extracted -> extracting` (recycle claim)
3. `extracting -> cleaned` (full successful content processing)
4. `extracting -> core_extracted` (unchanged hash short-circuit)
5. `extracting -> failed` (error path via `fail_scrape_job`)

Handoff:
- `cleaned` rows are consumed by core extraction worker.

---

## 7. Error Handling

Local processing exceptions:
- caught in `process_scrape_job`
- status set to `failed`
- `error_message` populated

Global loop exceptions:
- caught in `run_worker`
- worker sleeps 7s and resumes loop

Known limitations:
- no retry around page navigation or markdown conversion
- no per-stage timeout config exposed
- hash check compares to latest scrape hash without strong state filtering logic

---

## 8. Observability

Current observability:
- stdout logs
- structured events persisted to `scrape_log_events` via `log_scrape_event(...)`
- status transition events persisted by DB trigger on `scrapes.status`

Useful emitted values:
- scrape ID
- career page ID
- URL
- content hash
- status outcomes
- chunk totals and conversion outcome metadata
- error messages on failure paths (`scrape_failed`, `worker_error`)

---

## 9. Failure Modes and Recovery

### 9.1 Browser startup/navigation failure
Symptoms:
- `failed` rows with Playwright errors

Recovery:
- reinstall browser binaries (`playwright install`)
- verify network reachability for target domain
- reset target rows to `queued`

### 9.2 Low-quality markdown conversion
Symptoms:
- weak chunk quality, downstream extraction misses jobs

Recovery:
- tune HTML cleanup rules
- tune markdownification options
- adjust chunk size/overlap

### 9.3 Stuck `extracting` rows after crash
Symptoms:
- rows not advancing

Recovery:
- inspect old `extracting` rows
- manually reset to `queued` for reprocessing

---

## 10. Runtime Notes

Poll interval:
- 7 seconds when queue is empty or on loop error

Concurrency pattern:
- safe to run multiple worker instances due to optimistic lock update

Resource profile:
- browser-heavy
- CPU/memory depends on page complexity and Playwright runtime

---

## 11. Extension Points

High-value improvements:
- explicit per-site wait strategy (instead of fixed 5s sleep)
- richer unchanged-content detection policy
- structured logs and metrics
- stage-specific failure statuses (e.g., `content_extraction_failed`)

---

## 12. Related Docs
- `docs/SYSTEM_DOCUMENTATION.md`
- `docs/DATABASE_SYSTEM_DOCUMENTATION.md`
- `docs/WORKER_IMPORT_COMPANIES.md`
- `docs/WORKER_JOB_EXTRACTION.md`
