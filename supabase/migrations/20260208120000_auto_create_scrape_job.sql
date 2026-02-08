-- Migration: Auto-create scrape job on career_page insert
-- Description: Adds a trigger to automatically create a 'queued' scrape job when a new career page is added.
--             Also backfills any existing career pages that have no scrape jobs.

BEGIN;

-- 1. Create the Function
CREATE OR REPLACE FUNCTION create_initial_scrape_job()
RETURNS TRIGGER AS $$
BEGIN
  -- Insert a new scrape job with 'queued' status
  -- Note: The 'scrapes' table has another trigger (scrapes_fill_company) that runs BEFORE INSERT
  --       which will automatically populate the 'company_name' field.
  INSERT INTO scrapes (career_page_id, status)
  VALUES (NEW.id, 'queued');
  
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 2. Create the Trigger
DROP TRIGGER IF EXISTS trigger_create_initial_scrape_job ON career_pages;
CREATE TRIGGER trigger_create_initial_scrape_job
AFTER INSERT ON career_pages
FOR EACH ROW
EXECUTE FUNCTION create_initial_scrape_job();

-- 3. Backfill existing career pages
-- Insert a scrape job for any career page that doesn't have one yet.
INSERT INTO scrapes (career_page_id, status)
SELECT cp.id, 'queued'
FROM career_pages cp
WHERE NOT EXISTS (
    SELECT 1 FROM scrapes s WHERE s.career_page_id = cp.id
);

COMMIT;
