# Helper Module & Worker Documentation (`job_extraction.py`)

## 1. Overview
This module serves two purposes:
1.  **Library of Helpers**: Provides pure functions for cleaning, validating, and normalizing job data.
2.  **Extraction Worker**: specific entry point (`extract_jobs`) that orchestrates the AI extraction loop.

---

## 2. Helper Functions (Library)

### `clean_jobs(ai_results, company_id, scrape_id, base_url)`
The core normalization logic.
- **Input**: Raw JSON list from AI, metadata.
- **Output**: Tuple `(cleaned_jobs, error_messages)`.
- **Logic**:
    - Unwraps Markdown links in titles/URLs.
    - Resolves relative URLs against `base_url`.
    - Validates URL structure and prefixes.
    - Dedupes within the batch.

### `normalize_title(title)`
- Removes grouping chars like `[Title]` -> `Title`.
- Collapses whitespace.

### `valid_job_url(url)`
- Rejects non-http/non-relative strings.
- Rejects URLs with spaces.

### `unwrap_markdown_url(url)`
- Converts `[Link](http://...)` to `http://...`.

---

## 3. Worker Execution (`extract_jobs`)

### Entry Point
- `python3 job_extraction.py` runs `extract_jobs()`.
- Loops infinitely, polling for `cleaned` scrapes.

### Locking Model
- Uses `fetch_next_ready_job()` (optimistic lock) to claim a scrape.
- Transitions: `cleaned` -> `core_extracting` -> `core_extracted`.

### Observability & Logging
- **Optimization**: Fetches `company_id` and `career_page_id` once per scrape.
- Passes these IDs to all `log_scrape_event` calls to minimize DB load.
- Events logged:
    - `chunking_completed`
    - `jobs_extracted`
    - `jobs_upserted`
    - `scrape_failed`

---

## 4. Error Handling
- **LLM Failure**: If AI server is unreachable (pre-flight check), marks scrape as `core_extraction_failed` and sleeps 60s.
- **Processing Error**: Catches exceptions, logs `scrape_failed`, and marks scrape as `core_extraction_failed`.
- **Global Crash**: Outer loop catches unforeseen errors to keep worker alive.

---

## 5. Related Files
- `database/database.py`: DB interactions & locking.
- `database/AI_connection/AI.py`: LLM communication.
