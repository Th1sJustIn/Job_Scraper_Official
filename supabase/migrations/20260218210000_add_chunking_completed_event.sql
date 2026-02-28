-- Migration: Add chunking_completed to event_type check constraint
-- Description: Adds 'chunking_completed' to the allowed list of event types.

BEGIN;

-- Update event_type check constraint
ALTER TABLE scrape_log_events
DROP CONSTRAINT IF EXISTS scrape_log_events_event_type_chk;

ALTER TABLE scrape_log_events
ADD CONSTRAINT scrape_log_events_event_type_chk CHECK (
    event_type IN (
        'status_transition',
        'url_hit',            -- Deprecated but kept for compatibility
        'chunk_progress',
        'jobs_extracted',
        'jobs_upserted',
        'scrape_failed',
        'worker_error',
        'heartbeat',          -- Deprecated
        'fetch_started',
        'fetch_finished',
        'ai_extraction_finished',
        'job_description_extracted',
        'error',
        'chunking_completed'  -- NEW
    )
);

COMMIT;
