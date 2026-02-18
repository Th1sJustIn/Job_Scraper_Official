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

## 5. Data Cleaning
The worker performs specific HTML cleaning before storage:
- Removes standard noise tags (`script`, `style`, `noscript`, `svg`, `canvas`, `iframe`, `header`, `footer`, `nav`)
- Removes specific unwanted elements (e.g., `.iti__country-list` dropdowns)
- Normalizes whitespace

## 6. Edit Location for ATS Caps
Global ATS caps and pacing are editable in:
- `provider_fetch_control` table (`max_in_flight`, `base_delay_ms`, `jitter_max_ms`)

Changes apply to all workers without code edits.

## 6. ATS Limiting Mechanics

The ATS limiter is global across all worker instances and is enforced in SQL, not in local Python memory.

Flow per claim:
1. Candidate job URL is classified into a provider bucket using substring matching:
- `greenhouse`, `lever`, `ashby`, `workable`, `smartrecruiters`, `ycombinator`; otherwise `custom`.
2. `claim_next_job_page_fetch(...)` locks that provider row in `provider_fetch_control`.
3. Claim only proceeds when both are true:
- `in_flight < max_in_flight`
- `next_allowed_at IS NULL` or `next_allowed_at <= now()`
4. On successful claim:
- `in_flight` is incremented
- job lock is set (`jobs.content_status='job_extracting'`)
5. On completion (`complete_job_page_fetch(...)`):
- `in_flight` is decremented
- next pacing window is set:
  - `next_allowed_at = now() + base_delay_ms + random(0..jitter_max_ms)`

How to tune:
- Increase/decrease global parallelism for a provider:
  - edit `max_in_flight`
- Increase/decrease spacing between hits:
  - edit `base_delay_ms`
- Increase/decrease random spread between workers:
  - edit `jitter_max_ms`

Example SQL:
```sql
update provider_fetch_control
set max_in_flight = 2,
    base_delay_ms = 2000,
    jitter_max_ms = 1000,
    updated_at = now()
where provider_bucket = 'ashby';
```
