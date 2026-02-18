-- Migration: Fix remaining job_id ambiguity in claim_next_job_page_fetch
-- Description: Uses ON CONFLICT ON CONSTRAINT to avoid output-variable collision
--              with RETURNS TABLE job_id in PL/pgSQL function scope.
-- Idempotent: Uses OR REPLACE function definition

BEGIN;

CREATE OR REPLACE FUNCTION claim_next_job_page_fetch(p_worker_run_id TEXT DEFAULT NULL)
RETURNS TABLE (
    fetch_id BIGINT,
    job_id BIGINT,
    job_url TEXT,
    provider_bucket TEXT,
    host TEXT
)
LANGUAGE plpgsql
AS $$
DECLARE
    candidate RECORD;
    control_row provider_fetch_control%ROWTYPE;
    selected_bucket TEXT;
    locked_job_id BIGINT;
    locked_fetch_id BIGINT;
BEGIN
    FOR candidate IN
        SELECT
            j.id AS candidate_job_id,
            j.url AS candidate_job_url,
            lower(split_part(regexp_replace(j.url, '^https?://', ''), '/', 1)) AS candidate_host
        FROM jobs j
        WHERE j.status = 'open'
          AND j.last_seen_at >= (now() - INTERVAL '2 days')
          AND j.content_status = 'open'
          AND NOT EXISTS (
              SELECT 1
              FROM job_page_fetches jpf
              WHERE jpf.job_id = j.id
                AND (
                    jpf.status IN ('extracted', 'gone')
                    OR jpf.attempt_count >= 2
                )
          )
        ORDER BY j.last_seen_at DESC, j.id ASC
        LIMIT 200
    LOOP
        selected_bucket := classify_provider_bucket(candidate.candidate_job_url);

        SELECT *
        INTO control_row
        FROM provider_fetch_control pfc
        WHERE pfc.provider_bucket = selected_bucket
        FOR UPDATE;

        IF NOT FOUND THEN
            CONTINUE;
        END IF;

        IF control_row.in_flight >= control_row.max_in_flight THEN
            CONTINUE;
        END IF;

        IF control_row.next_allowed_at IS NOT NULL AND control_row.next_allowed_at > now() THEN
            CONTINUE;
        END IF;

        UPDATE jobs
        SET
            content_status = 'job_extracting',
            content_status_updated_at = now()
        WHERE id = candidate.candidate_job_id
          AND content_status = 'open'
        RETURNING id INTO locked_job_id;

        IF locked_job_id IS NULL THEN
            CONTINUE;
        END IF;

        INSERT INTO job_page_fetches (
            job_id,
            job_url,
            provider_bucket,
            host,
            status,
            attempt_count,
            worker_run_id,
            updated_at
        )
        VALUES (
            locked_job_id,
            candidate.candidate_job_url,
            selected_bucket,
            candidate.candidate_host,
            'extracting',
            1,
            p_worker_run_id,
            now()
        )
        ON CONFLICT ON CONSTRAINT job_page_fetches_job_id_key DO UPDATE
        SET
            job_url = EXCLUDED.job_url,
            provider_bucket = EXCLUDED.provider_bucket,
            host = EXCLUDED.host,
            status = 'extracting',
            attempt_count = job_page_fetches.attempt_count + 1,
            worker_run_id = EXCLUDED.worker_run_id,
            error_message = NULL,
            updated_at = now()
        RETURNING id INTO locked_fetch_id;

        UPDATE provider_fetch_control pfc
        SET
            in_flight = pfc.in_flight + 1,
            last_outcome = 'claimed',
            updated_at = now()
        WHERE pfc.provider_bucket = selected_bucket;

        RETURN QUERY
        SELECT
            locked_fetch_id,
            locked_job_id,
            candidate.candidate_job_url,
            selected_bucket,
            candidate.candidate_host;
        RETURN;
    END LOOP;

    RETURN;
END;
$$;

COMMIT;
