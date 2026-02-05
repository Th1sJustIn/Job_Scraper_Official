from supabase.client import Client
from database.client import get_supabase_client

supabase: Client = get_supabase_client()

def get_career_page_url(career_page_id: int) -> str:
    """Get the URL of a career page from the database."""
    response = supabase.table("career_pages").select("url").eq("id", career_page_id).execute()
    return response.data[0]["url"]

def get_career_pages() -> list[dict]:
    """Get all career pages from the database."""
    response = supabase.table("career_pages").select("*").execute()
    return response.data

def create_scrape_job(career_page_id: int) -> int:
    """Create a new scrape job with status 'queued'."""
    response = supabase.table("scrapes").insert({
        "career_page_id": career_page_id,
        "status": "queued"
    }).execute()

    return response.data[0]["id"]

def update_scrape_job(scrape_id: int, raw_html: str, markdown: str, chunks: list, chunk_count: int, html_hash: str = None):
    """Update a scrape job with results and mark as 'completed'."""
    supabase.table("scrapes").update({
        "raw_html": raw_html,
        "markdown": markdown,
        "chunks_json": chunks,
        "chunk_count": chunk_count,
        "html_hash": html_hash,
        "status": "cleaned"
    }).eq("id", scrape_id).execute()

def fail_scrape_job(scrape_id: int, error_message: str):
    """Mark a scrape job as 'failed' with an error message."""
    supabase.table("scrapes").update({
        "status": "failed",
        "error_message": error_message
    }).eq("id", scrape_id).execute()

def update_scrape_status(scrape_id: int, status: str):
    """Update the status of a scrape job."""
    supabase.table("scrapes").update({
        "status": status
    }).eq("id", scrape_id).execute()

from datetime import datetime, timedelta, timezone

from typing import Optional

def get_latest_scrape_hash(career_page_id: int) -> Optional[str]:
    """Get the html_hash of the latest successful scrape for a career page."""
    response = supabase.table("scrapes")\
        .select("html_hash")\
        .eq("career_page_id", career_page_id)\
        .neq("html_hash", "null")\
        .order("created_at", desc=True)\
        .limit(1)\
        .execute()
    
    if response.data:
        return response.data[0]["html_hash"]
    return None


def is_recently_scraped(career_page_id: int, hours: int = 20) -> bool:
    """Check if the career page was successfully scraped within the last `hours`."""
    time_threshold = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    
    # .neq("status", "failed")\
    response = supabase.table("scrapes")\
        .select("id")\
        .eq("career_page_id", career_page_id)\
        .gte("created_at", time_threshold)\
        .limit(1)\
        .execute()
    
    return len(response.data) > 0

def get_cleaned_scrapes() -> list[dict]:
    """Get all scrapes with status 'cleaned'."""
    response = supabase.table("scrapes").select("id, chunks_json, chunk_count, career_pages(company_id)").eq("status", "cleaned").execute()
    return response.data

def insert_jobs(jobs_data: list[dict]):
    """
    Insert or update jobs in the database.
    Expects a list of dicts matching the 'jobs' table schema.
    Uses upsert based on (company_id, url) constraint.
    """
    if not jobs_data:
        return

    # Using upsert to handle duplicates.
    # If the job exists (same company_id and url), we update last_seen_at.
    # We might want to update status to "open" just in case it was closed?
    # For now, let's just upsert the whole record which effectively updates it.
    
    response = supabase.table("jobs").upsert(jobs_data, on_conflict="company_id, url").execute()
    return response.data

def fetch_next_ready_job() -> Optional[dict]:
    """
    Atomically fetches one 'cleaned' job, marks it as 'core_extracting',
    and returns its details (including nested career_pages info).
    Uses optimistic locking pattern.
    """
    # Fetch a candidate
    candidates = supabase.table("scrapes").select("id, chunks_json, chunk_count, career_pages(company_id)")\
        .eq("status", "cleaned")\
        .limit(1)\
        .execute()

    if not candidates.data:
        return None
    
    candidate = candidates.data[0]
    scrape_id = candidate["id"]
    
    # Attempt to lock: Update status ONLY IF it is still 'cleaned'
    response = supabase.table("scrapes").update({"status": "core_extracting"})\
        .eq("id", scrape_id)\
        .eq("status", "cleaned")\
        .execute()
    
    # If the update returned data, we successfully claimed the lock
    if len(response.data) > 0:
        return candidate
    
    # If we didn't get it (someone else did), return None (caller will retry)
    return None


def fetch_next_scrape_job() -> Optional[dict]:
    """
    Atomically fetches one scrape job for content extraction.
    Logic:
    1. Finds a 'queued' job.
    2. OR finds a 'core_extracted' job older than 24 hours (recycling it).
    3. Updates status to 'extracting' and bumps 'created_at' to now (to reset the 24h timer).
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    
    # 1. Try 'queued'
    response = supabase.table("scrapes").select("id, career_page_id")\
        .eq("status", "queued")\
        .limit(1)\
        .execute()
    
    target_id = None
    original_status = None
    
    if response.data:
        target_id = response.data[0]["id"]
        original_status = "queued"
    else:
        # 2. Try 'core_extracted' > 24h
        # We need to filter for old jobs.
        threshold = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        
        response = supabase.table("scrapes").select("id, career_page_id")\
            .eq("status", "core_extracted")\
            .lt("created_at", threshold)\
            .limit(1)\
            .execute()
        
        if response.data:
            target_id = response.data[0]["id"]
            original_status = "core_extracted"

    if target_id:
        # Atomic lock
        # We update created_at to NOW so it doesn't get picked up again immediately 
        # (effectively treating it as a new scrape)
        update_payload = {
            "status": "extracting",
            "created_at": now_iso
        }
        
        res = supabase.table("scrapes").update(update_payload)\
            .eq("id", target_id)\
            .eq("status", original_status)\
            .execute()
            
        if res.data:
            return res.data[0]

    return None

