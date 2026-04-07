-- Migration: Add description_skipped status to job_page_fetches
-- Description: Allows marking roles as skipped based on title filtering (e.g., senior/manager).

BEGIN;

ALTER TABLE job_page_fetches
DROP CONSTRAINT IF EXISTS job_page_fetches_status_chk;

ALTER TABLE job_page_fetches
ADD CONSTRAINT job_page_fetches_status_chk
CHECK (status IN (
    'queued', 
    'extracting', 
    'extracted', 
    'failed', 
    'gone', 
    'blocked', 
    'description_extracting', 
    'description_extracted', 
    'description_extraction_failed',
    'description_skipped'
));

COMMIT;
