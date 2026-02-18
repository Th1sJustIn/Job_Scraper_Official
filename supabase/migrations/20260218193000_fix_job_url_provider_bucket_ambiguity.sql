-- Migration: Fix provider_bucket ambiguity in job URL worker SQL functions
-- Description: Qualifies provider_fetch_control.provider_bucket references to avoid
--              PL/pgSQL variable/column ambiguity (SQLSTATE 42702).
-- Idempotent: Uses OR REPLACE function definitions

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
        ON CONFLICT (job_id) DO UPDATE
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

CREATE OR REPLACE FUNCTION complete_job_page_fetch(
    p_fetch_id BIGINT,
    p_status TEXT,
    p_exists_verified BOOLEAN DEFAULT FALSE,
    p_http_status INTEGER DEFAULT NULL,
    p_final_url TEXT DEFAULT NULL,
    p_content_type TEXT DEFAULT NULL,
    p_raw_html TEXT DEFAULT NULL,
    p_markdown TEXT DEFAULT NULL,
    p_html_hash TEXT DEFAULT NULL,
    p_error_message TEXT DEFAULT NULL
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    fetch_row job_page_fetches%ROWTYPE;
    control_row provider_fetch_control%ROWTYPE;
    delay_ms INTEGER;
    next_status TEXT;
    next_job_status TEXT;
    final_fetch_status TEXT;
BEGIN
    IF p_status NOT IN ('extracted', 'failed', 'gone', 'blocked') THEN
        RAISE EXCEPTION 'Invalid completion status: %', p_status;
    END IF;

    SELECT *
    INTO fetch_row
    FROM job_page_fetches
    WHERE id = p_fetch_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RETURN;
    END IF;

    SELECT *
    INTO control_row
    FROM provider_fetch_control pfc
    WHERE pfc.provider_bucket = fetch_row.provider_bucket
    FOR UPDATE;

    final_fetch_status := p_status;
    next_status := 'open';
    next_job_status := 'open';

    IF p_status = 'extracted' THEN
        final_fetch_status := 'extracted';
        next_status := 'job_extracted';
        next_job_status := 'open';
    ELSIF fetch_row.attempt_count >= 2 THEN
        final_fetch_status := 'gone';
        next_status := 'open';
        next_job_status := 'closed';
    END IF;

    UPDATE job_page_fetches
    SET
        status = final_fetch_status,
        exists_verified = COALESCE(p_exists_verified, FALSE),
        http_status = p_http_status,
        final_url = p_final_url,
        content_type = p_content_type,
        raw_html = p_raw_html,
        markdown = p_markdown,
        html_hash = p_html_hash,
        error_message = p_error_message,
        updated_at = now(),
        extracted_at = CASE WHEN final_fetch_status = 'extracted' THEN now() ELSE extracted_at END
    WHERE id = p_fetch_id;

    UPDATE jobs
    SET
        status = next_job_status,
        content_status = next_status,
        content_status_updated_at = now()
    WHERE id = fetch_row.job_id;

    IF FOUND AND control_row.provider_bucket IS NOT NULL THEN
        delay_ms := control_row.base_delay_ms + FLOOR(random() * (control_row.jitter_max_ms + 1))::INTEGER;

        UPDATE provider_fetch_control pfc
        SET
            in_flight = GREATEST(pfc.in_flight - 1, 0),
            next_allowed_at = now() + ((delay_ms::TEXT || ' milliseconds')::INTERVAL),
            last_outcome = final_fetch_status,
            updated_at = now()
        WHERE pfc.provider_bucket = fetch_row.provider_bucket;
    END IF;
END;
$$;

COMMIT;
