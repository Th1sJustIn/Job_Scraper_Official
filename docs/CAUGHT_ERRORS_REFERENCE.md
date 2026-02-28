# Caught Errors Reference

This file lists the current error paths that are explicitly caught in the codebase and what the system does when each one happens.

## `job_extraction.py`

### Per-job field processing catch
- Location: `clean_jobs(...)` inner `except Exception as e`
- Trigger: malformed job payloads (bad types, missing fields, unexpected data shape during normalization)
- Behavior:
- appends a skip message to `error_messages`
- continues processing remaining jobs

### Upsert stats parsing catch
- Location: `process_scrape(...)` around `datetime.fromisoformat(first_seen)`
- Trigger: bad/missing timestamp in returned upsert row
- Behavior:
- falls back to counting row as `updated_count`
- no worker failure

### LLM connectivity failure catch
- Location: `extract_jobs()` `except LLMConnectionError as e`
- Raised from: `database/AI_connection/AI.py::ensure_llm_server_available()`
- Trigger examples:
- invalid `OLLAMA_URL` format
- `curl --fail ... /api/tags` non-zero exit (connection refused, timeout, HTTP failure)
- Behavior:
- logs error
- logs structured event (`event_type="scrape_failed"`) via `log_scrape_event(...)`
- sets scrape status via `fail_scrape_job(..., status="core_extraction_failed")`
- sleeps 60 seconds before next loop iteration

### Generic scrape processing catch
- Location: `extract_jobs()` `except Exception as e` (inner per-scrape block)
- Trigger: any unhandled error during `process_scrape(scrape)`
- Behavior:
- logs error
- logs structured event (`event_type="scrape_failed"`) via `log_scrape_event(...)`
- sets scrape status via `fail_scrape_job(..., status="core_extraction_failed")`

### Global worker loop catch
- Location: `extract_jobs()` outer `except Exception as e`
- Trigger: unexpected loop-level failures (fetching jobs, unhandled runtime errors)
- Behavior:
- logs `Unexpected global error`
- if scrape context exists, logs structured event (`event_type="worker_error"`) via `log_scrape_event(...)`
- sleeps 5 seconds and continues loop

## `database/AI_connection/AI.py`

### AI extraction retry catch
- Location: `extract_jobs_from_chunk(...)` `except Exception as e` inside retry loop
- Trigger examples:
- request/transport failures to LLM chat endpoint
- invalid response shape (missing keys in JSON)
- JSON parse failures when loading model output
- Behavior:
- logs attempt failure
- retries once (2 attempts total)
- returns `[]` after retries are exhausted

## `extract_site_content.py`

### Navigation wait fallback catches
- Location: `navigate_and_capture_html(...)` inner `except Exception` blocks
- Trigger:
- `networkidle` timeout/failure after `domcontentloaded`
- selector wait misses/failures during fallback (`main`, `[role='main']`, `section`, `body`)
- Behavior:
- suppresses wait-stage errors
- falls back to next readiness strategy
- still captures page HTML for downstream processing

### Per-scrape job catch
- Location: `process_scrape_job(...)` `except Exception as e`
- Trigger: any error during page fetch, parsing, normalization, chunking, or DB update
- Behavior:
- logs error
- logs structured event (`event_type="scrape_failed"`) via `log_scrape_event(...)`
- marks scrape as failed via `fail_scrape_job(scrape_id, str(e))` (default status: `failed`)
- returns a boolean that can trigger browser recycle for fatal browser-close style errors

### Context close cleanup catch
- Location: `process_scrape_job(...)` `finally` inner `except Exception`
- Trigger: Playwright context close failure during cleanup
- Behavior:
- suppresses cleanup exception
- prevents cleanup errors from interrupting worker loop

### Global worker loop catch
- Location: `run_worker()` `except Exception as e`
- Trigger: unexpected loop-level failures
- Behavior:
- logs `Global worker error`
- if job context exists, logs structured event (`event_type="worker_error"`) via `log_scrape_event(...)`
- sleeps 7 seconds and continues loop

### Browser close cleanup catch
- Location: `run_worker()` recycle path inner `except Exception`
- Trigger: Playwright browser close failure during browser recycle
- Behavior:
- suppresses cleanup exception
- attempts fresh browser launch and continues loop

## `extract_job_url_content.py`

### Navigation wait fallback catches
- Location: `navigate_and_capture(...)` inner `except Exception` blocks
- Trigger:
- `networkidle` timeout/failure after `domcontentloaded`
- selector wait misses/failures during fallback (`main`, `[role='main']`, `section`, `body`)
- Behavior:
- suppresses wait-stage errors
- falls back to next readiness strategy
- still captures page HTML for existence/content handling

### Per-job fetch catch
- Location: `process_job_content(...)` `except Exception as e`
- Trigger: any unhandled error during page fetch, validation, conversion, hashing, or completion writeback
- Behavior:
- logs error
- marks job-page fetch as `failed` through DB completion function
- resets `jobs.content_status` back to `open` (requeue)
- returns a boolean that can trigger browser recycle for fatal browser-close style errors

### Context close cleanup catch
- Location: `process_job_content(...)` `finally` inner `except Exception`
- Trigger: Playwright context close failure during cleanup
- Behavior:
- suppresses cleanup exception
- prevents cleanup errors from interrupting worker loop

### Global worker loop catch
- Location: `run_worker()` `except Exception as e`
- Trigger: unexpected loop-level failures
- Behavior:
- logs `Global worker error`
- sleeps 7 seconds and continues loop

### Browser close cleanup catch
- Location: `run_worker()` recycle path inner `except Exception`
- Trigger: Playwright browser close failure during browser recycle
- Behavior:
- suppresses cleanup exception
- attempts fresh browser launch and continues loop

## `database/database.py`

### Structured event persistence catch
- Location: `log_scrape_event(...)` `except Exception as e`
- Trigger examples:
- missing `scrape_log_events` relation before migration is applied
- insert/select failures against Supabase
- unexpected payload type/shape issues
- Behavior:
- logs warning: `Warning: failed to persist scrape event for scrape ...`
- does not re-raise, preserving worker execution path

## `import_companies.py`

### CSV file missing catch
- Location: `import_companies(...)` `except FileNotFoundError`
- Trigger: provided CSV path does not exist
- Behavior:
- logs file-not-found message
- exits function

### Generic import catch
- Location: `import_companies(...)` `except Exception as e`
- Trigger: any unhandled runtime/import/database error in the import process
- Behavior:
- logs generic error message
- exits function

## Quick Log-to-Handler Lookup

- `LLM connectivity check failed for .../api/tags` -> `job_extraction.py` LLM catch -> status `core_extraction_failed`, 60s sleep
- `Error extracting jobs from AI (attempt X/2)` -> `database/AI_connection/AI.py` retry catch
- `Error processing scrape ...` (job extraction worker) -> `job_extraction.py` per-scrape catches -> status `core_extraction_failed`
- `Global worker error:` -> `extract_site_content.py` loop catch
- `Global worker error:` (job URL worker) -> `extract_job_url_content.py` loop catch
- `Unexpected global error:` -> `job_extraction.py` loop catch
- `Warning: failed to persist scrape event for scrape ...` -> `database/database.py::log_scrape_event(...)` catch
- `Error: File '...' not found.` -> `import_companies.py` file-not-found catch
