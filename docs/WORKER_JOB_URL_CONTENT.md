# Job URL Content Worker Documentation (`extract_job_url_content.py`)

## 1. Purpose
This worker fetches content from `jobs.url`, verifies the URL exists, stores cleaned page content, and enforces global ATS throttling so multiple workers do not over-hit the same provider.

## 2. Queue and Locking Model

Queue source:
- `jobs` table

Eligibility:
- `jobs.status='open'`
- `jobs.last_seen_at >= now() - 2 days`
- `jobs.content_status='open'`

Atomic claim:
- SQL function `claim_next_job_page_fetch(...)`:
  - classifies provider bucket by URL substring (`ashby`, `lever`, `greenhouse`, `workable`, `smartrecruiters`, `ycombinator`, else `custom`)
  - enforces `provider_fetch_control` caps/pacing
  - atomically updates `jobs.content_status` from `open -> job_extracting`
  - creates/updates `job_page_fetches` row as `extracting`

Completion:
- SQL function `complete_job_page_fetch(...)`:
  - updates `job_page_fetches` terminal status (`extracted|failed|gone|blocked`)
  - increments/uses `attempt_count` to enforce retry policy
  - updates `jobs.content_status`:
    - `job_extracted` on `extracted`
    - `open` on first non-success (`failed|gone|blocked`) so one retry is allowed
  - after second non-success attempt:
    - force terminal `job_page_fetches.status='gone'`
    - set `jobs.status='closed'`
    - keep `jobs.content_status='open'` (non-claimable due to closed status)
  - decrements provider `in_flight` and sets next allowed request time.

## 3. Runtime Safeguards
- staged navigation (`domcontentloaded` + best-effort `networkidle` + selector fallback)
- browser context isolation per job
- browser recycle after threshold or fatal browser errors
- per-job and global exception guards with sleep-and-continue loop

## 4. Existence Rule
A job page is considered existing only when:
- final response status is `2xx`
- response body/content looks like HTML

Non-success mapping:
- `404/410` -> `gone`
- `403/429` or anti-bot patterns -> `blocked`
- other failures -> `failed`

## 5. Edit Location for ATS Caps
Global ATS caps and pacing are editable in:
- `provider_fetch_control` table (`max_in_flight`, `base_delay_ms`, `jitter_max_ms`)

Changes apply to all workers without code edits.
