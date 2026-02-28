-- Migration: Optimize scrape_log_events schema
-- Description: Changes worker_run_id to TEXT and adds operational event types.
-- Handles view dependencies by dropping and recreating scrape_event_feed_v.

BEGIN;

-- 1. Drop dependent views that use worker_run_id
DROP VIEW IF EXISTS scrape_event_feed_v;

-- 2. Change worker_run_id to TEXT to support "job-url-content-TIMESTAMP" format
ALTER TABLE scrape_log_events
ALTER COLUMN worker_run_id TYPE TEXT USING worker_run_id::TEXT;

-- 3. Update event_type check constraint to include new operational types
ALTER TABLE scrape_log_events
DROP CONSTRAINT IF EXISTS scrape_log_events_event_type_chk;

ALTER TABLE scrape_log_events
ADD CONSTRAINT scrape_log_events_event_type_chk CHECK (
    event_type IN (
        'status_transition',
        'url_hit',            -- Deprecated but kept for compatibility during rollout
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
        'error'
    )
);

-- 4. Re-create scrape_event_feed_v with the new column type
CREATE OR REPLACE VIEW scrape_event_feed_v AS
SELECT
    e.id,
    e.created_at,
    e.scrape_id,
    e.career_page_id,
    COALESCE(e.company_id, cp.company_id) AS company_id,
    co.name AS company_name,
    cp.url AS career_page_url,
    e.worker,
    e.event_type,
    e.severity,
    e.from_status,
    e.to_status,
    e.message,
    e.metrics,
    e.worker_run_id
FROM scrape_log_events e
LEFT JOIN career_pages cp ON cp.id = e.career_page_id
LEFT JOIN companies co ON co.id = COALESCE(e.company_id, cp.company_id);

-- 5. Restore permissions (if role exists)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'emmet_readonly') THEN
        GRANT SELECT ON scrape_event_feed_v TO emmet_readonly;
    END IF;
END;
$$;

COMMIT;
