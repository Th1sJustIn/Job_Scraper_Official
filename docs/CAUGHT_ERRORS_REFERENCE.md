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

### Generic scrape processing catch
- Location: `extract_jobs()` `except Exception as e` (inner per-scrape block)
- Trigger: any unhandled error during `process_scrape(scrape)`
- Behavior:
- logs error
- sets scrape status via `fail_scrape_job(...)` (default status: `failed`)
- logs structured event (`event_type="scrape_failed"`) via `log_scrape_event(...)`

### Global worker loop catch
- Location: `extract_jobs()` outer `except Exception as e`
- Trigger: unexpected loop-level failures (fetching jobs, unhandled runtime errors)
- Behavior:
- logs `Unexpected global error`
- if scrape context exists, logs structured event (`event_type="worker_error"`) via `log_scrape_event(...)`
- sleeps 5 seconds and continues loop

## `extract_site_content.py`

### Per-scrape job catch
- Location: `process_scrape_job(...)` `except Exception as e`
- Trigger: any error during page fetch, parsing, normalization, chunking, or DB update
- Behavior:
- logs error
- logs structured event (`event_type="scrape_failed"`) via `log_scrape_event(...)`
- marks scrape as failed via `fail_scrape_job(scrape_id, str(e))` (default status: `failed`)

### Global worker loop catch
- Location: `run_worker()` `except Exception as e`
- Trigger: unexpected loop-level failures
- Behavior:
- logs `Global worker error`
- if job context exists, logs structured event (`event_type="worker_error"`) via `log_scrape_event(...)`
- sleeps 7 seconds and continues loop

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

- `Error extracting jobs from AI (attempt X/2)` -> `database/AI_connection/AI.py` retry catch
- `Error processing scrape ...` (job extraction worker) -> `job_extraction.py` per-scrape catch -> `failed`
- `Global worker error:` -> `extract_site_content.py` loop catch
- `Unexpected global error:` -> `job_extraction.py` loop catch
- `Warning: failed to persist scrape event for scrape ...` -> `database/database.py::log_scrape_event(...)` catch
- `Error: File '...' not found.` -> `import_companies.py` file-not-found catch
