-- Migration: Create job_descriptions table
-- Description: Stores structured data extracted from job page markdown by AI
-- Idempotent: Uses IF NOT EXISTS

BEGIN;

CREATE TABLE IF NOT EXISTS job_descriptions (
    job_id BIGINT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
    
    summary TEXT,
    
    responsibilities TEXT[],
    requirements TEXT[],
    preferred_requirements TEXT[],
    tech_stack TEXT[],
    
    experience_level TEXT,
    is_entry_level BOOLEAN,
    
    years_experience_min NUMERIC,
    years_experience_max NUMERIC,
    
    employment_type TEXT,
    internship BOOLEAN,
    
    salary_min NUMERIC,
    salary_max NUMERIC,
    salary_currency TEXT,
    
    visa_sponsorship BOOLEAN,
    remote_policy TEXT,
    team TEXT,
    degree_required BOOLEAN,
    
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE job_descriptions IS 'Stores structured job description data extracted via AI from job page markdown';

COMMIT;
