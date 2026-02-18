# Database System Documentation (Supabase/Postgres)

## 1. Purpose
This document describes the database layer that drives the job scraper pipeline: schema design, migration order, triggers, queue-state semantics, locking patterns, and operational recovery actions.

---

## 2. Platform and Access

Platform:
- Supabase (Postgres)

Client integration:
- `database/client.py` creates the client from env vars:
  - `SUPABASE_PROJECT_URL`
  - `SUPABASE_SECRET_KEY` or `SUPABASE_API_KEY`

Access style:
- all worker scripts perform table operations through Supabase Python client.

---

## 3. Migration Inventory and Order

Migrations (current repository order):
1. `20250131120000_create_companies.sql`
2. `20250131120500_create_career_pages.sql`
3. `20250131121000_create_scrapes.sql`
4. `20250201132500_add_company_name_to_scrapes.sql`
5. `20250201195600_create_jobs.sql`
6. `20260208120000_auto_create_scrape_job.sql`

Operational note:
- trigger-based queue initialization depends on both `career_pages` and `scrapes` existing.

---

## 4. Schema Details

## 4.1 `companies`
Definition:
- PK `id` BIGINT identity
- `name` TEXT NOT NULL UNIQUE

Role:
- canonical company table

Integrity guarantees:
- unique company names

## 4.2 `career_pages`
Definition:
- PK `id` BIGINT identity
- FK `company_id` -> `companies.id`
- `url` TEXT NOT NULL
- metadata:
  - `last_hash`
  - `last_updated`
  - `status` default `new`
- unique `(company_id, url)`

Role:
- source registry of pages to scrape

## 4.3 `scrapes`
Definition:
- PK `id` BIGINT identity
- FK `career_page_id` -> `career_pages.id`
- content fields:
  - `raw_html`
  - `markdown`
  - `chunks_json` (JSONB)
  - `chunk_count`
  - `html_hash`
- execution/status fields:
  - `status` (migration default `fetched`)
  - `error_message`
  - `company_name` (added later via migration/trigger)
  - `created_at` timestamptz default now

Role:
- work queue + historical scrape attempt store

## 4.4 `jobs`
Definition:
- PK `id` BIGINT identity
- FK `company_id` -> `companies.id`
- payload:
  - `title` (required)
  - `location`
  - `department`
  - `url` (required)
  - `content_hash`
  - `raw_scrape_id`
- lifecycle:
  - `status` default `open`
  - `first_seen_at`, `last_seen_at`
- unique `(company_id, url)`

Role:
- deduplicated extracted job postings

---

## 5. Trigger System

## 5.1 Scrape Company Name Trigger
Migration:
- `20250201132500_add_company_name_to_scrapes.sql`

Components:
- function: `set_scrape_company_name()`
- trigger: `scrapes_fill_company` (`BEFORE INSERT` on `scrapes`)

Behavior:
- resolves `companies.name` via `career_pages.company_id`
- writes that name into `scrapes.company_name`

Backfill:
- migration updates existing rows with null `company_name`.

## 5.2 Initial Scrape Job Trigger
Migration:
- `20260208120000_auto_create_scrape_job.sql`

Components:
- function: `create_initial_scrape_job()`
- trigger: `trigger_create_initial_scrape_job` (`AFTER INSERT` on `career_pages`)

Behavior:
- inserts a new `scrapes` row with `status='queued'` whenever a new career page is inserted

Backfill:
- inserts `queued` scrape rows for any legacy career pages with no scrape rows.

---

## 6. Queue-State Semantics (`scrapes.status`)

Runtime statuses actively used by workers:
- `queued`
- `extracting`
- `cleaned`
- `core_extracting`
- `core_extracted`
- `failed`

Legacy/default status:
- `fetched` (table default in initial migration; typically bypassed by worker trigger/update flow)

---

## 7. State Machine and Worker Ownership

### 7.1 Full Transition Set
1. `none -> queued`
   - owner: DB trigger on `career_pages` insert

2. `queued -> extracting`
   - owner: site content worker claim

3. `core_extracted -> extracting`
   - owner: site content worker recycle claim (>24h old rows)

4. `extracting -> cleaned`
   - owner: site content worker successful content pipeline

5. `extracting -> core_extracted`
   - owner: site content worker unchanged-hash short-circuit

6. `extracting -> failed`
   - owner: site content worker error path

7. `cleaned -> core_extracting`
   - owner: core extraction worker claim

8. `core_extracting -> core_extracted`
   - owner: core extraction worker success path

9. `core_extracting -> failed`
   - owner: core extraction worker error path

### 7.2 Canonical Happy Path
`queued -> extracting -> cleaned -> core_extracting -> core_extracted`

---

## 8. Locking and Concurrency Control

Model:
- optimistic locking via conditional `UPDATE ... WHERE status=<expected>`

Pattern used in code:
1. select candidate row by desired status.
2. update same row to claimed status with status guard.
3. only proceed if update returned data.

Benefits:
- avoids duplicate claims across parallel workers.

Known caveat:
- interrupted workers can leave rows stuck in in-progress states (`extracting`, `core_extracting`) without automatic timeout recovery.

---

## 9. Data Integrity and Deduplication

Guaranteed by DB constraints:
- unique company names (`companies.name`)
- unique career page by company (`career_pages(company_id, url)`)
- unique job posting URL by company (`jobs(company_id, url)`)

Application-level guarantees:
- job upserts use `on_conflict="company_id, url"`
- in-batch dedupe before upsert

---

## 10. Query Patterns in Runtime Code

Common reads:
- get career page URL by ID
- fetch latest hash for page
- fetch next queued or recyclable scrape
- fetch next cleaned scrape for core extraction

Common writes:
- insert company/career page
- update scrape content and status
- fail scrape with `error_message`
- upsert jobs

---

## 11. Operational SQL Runbook

Use these patterns in Supabase SQL editor for diagnostics/recovery.

### 11.1 Inspect scrape status distribution
```sql
select status, count(*) 
from scrapes
group by status
order by count(*) desc;
```

### 11.2 Find potentially stuck in-progress rows
```sql
select id, career_page_id, status, created_at, error_message
from scrapes
where status in ('extracting', 'core_extracting')
order by created_at asc;
```

### 11.3 Requeue failed or stuck rows
```sql
update scrapes
set status = 'queued', error_message = null
where id in (<comma_separated_ids>);
```

### 11.4 Check rows ready for core extraction
```sql
select id, career_page_id, chunk_count, created_at
from scrapes
where status = 'cleaned'
order by created_at asc
limit 50;
```

### 11.5 Validate job dedupe key
```sql
select company_id, url, count(*)
from jobs
group by company_id, url
having count(*) > 1;
```

---

## 12. Failure Modes and DB-Level Recovery

### 12.1 Trigger missing or broken
Symptoms:
- new `career_pages` entries do not create `scrapes` rows

Recovery:
- reapply trigger migration
- manually backfill missing `queued` rows

### 12.2 Status drift / mixed legacy states
Symptoms:
- rows remaining in rarely used states (e.g. `fetched`)

Recovery:
- define migration or one-time normalization update to approved runtime statuses

### 12.3 Queue starvation
Symptoms:
- workers report no jobs despite expected activity

Recovery:
- inspect status counts
- verify claim conditions
- requeue eligible rows

---

## 13. Recommended Hardening

1. Add status check constraints or enum-like enforcement for `scrapes.status`.
2. Add index coverage for hot queue predicates:
- `scrapes(status, created_at)`
- `scrapes(career_page_id, created_at desc)`
3. Add stale-lease recovery job for in-progress statuses.
4. Add structured event table for worker state transitions.

---

## 14. Related Docs
- `docs/SYSTEM_DOCUMENTATION.md`
- `docs/WORKER_IMPORT_COMPANIES.md`
- `docs/WORKER_EXTRACT_SITE_CONTENT.md`
- `docs/WORKER_JOB_EXTRACTION.md`

