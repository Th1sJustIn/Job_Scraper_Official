-- Migration: Expand job_page_fetches status constraint
-- Description: Allows description_extracting, description_extracted, and description_extraction_failed statuses.

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
    'description_extraction_failed'
));

COMMIT;
