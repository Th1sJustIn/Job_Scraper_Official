-- Migration: Add company_name to scrapes table and create trigger
-- Description: Adds company_name column, sets up a trigger to auto-populate it, and includes a backfill step.

BEGIN;

-- 1. Add the column
ALTER TABLE scrapes ADD COLUMN IF NOT EXISTS company_name TEXT;

-- 2. Create the Trigger Function
-- Postgres requires a function for triggers
CREATE OR REPLACE FUNCTION set_scrape_company_name()
RETURNS TRIGGER AS $$
BEGIN
  NEW.company_name := (
    SELECT c.name
    FROM companies c
    JOIN career_pages cp ON cp.company_id = c.id
    WHERE cp.id = NEW.career_page_id
  );
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 3. Create the Trigger
DROP TRIGGER IF EXISTS scrapes_fill_company ON scrapes;
CREATE TRIGGER scrapes_fill_company
BEFORE INSERT ON scrapes
FOR EACH ROW
EXECUTE FUNCTION set_scrape_company_name();

-- 4. Backfill existing records (Running this in the migration usually ensures data consistency immediately)
UPDATE scrapes
SET company_name = (
  SELECT c.name
  FROM companies c
  JOIN career_pages cp ON cp.company_id = c.id
  WHERE cp.id = scrapes.career_page_id
)
WHERE company_name IS NULL;

COMMIT;
