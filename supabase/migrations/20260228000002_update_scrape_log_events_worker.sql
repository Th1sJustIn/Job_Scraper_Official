-- Migration: Expand scrape_log_events worker constraint
-- Description: Allows description_extraction_worker and job_url_content_worker to log events.

BEGIN;

ALTER TABLE scrape_log_events
DROP CONSTRAINT IF EXISTS scrape_log_events_worker_chk;

ALTER TABLE scrape_log_events
ADD CONSTRAINT scrape_log_events_worker_chk
CHECK (worker IN (
    'import_worker', 
    'site_content_worker', 
    'core_extraction_worker', 
    'system',
    'job_url_content_worker',
    'description_extraction_worker'
));

COMMIT;
