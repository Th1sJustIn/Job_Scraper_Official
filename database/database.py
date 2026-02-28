from supabase.client import Client
from database.client import get_supabase_client

supabase: Client = get_supabase_client()

def get_career_page_url(career_page_id: int) -> str:
    """Get the URL of a career page from the database."""
    response = supabase.table("career_pages").select("url").eq("id", career_page_id).execute()
    return response.data[0]["url"]

from typing import Optional, List, Dict, Any

def get_career_pages() -> List[Dict]:
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

def update_scrape_job(scrape_id: int, raw_html: str, markdown: str, chunks: List, chunk_count: int, html_hash: str = None):
    """Update a scrape job with results and mark as 'completed'."""
    supabase.table("scrapes").update({
        "raw_html": raw_html,
        "markdown": markdown,
        "chunks_json": chunks,
        "chunk_count": chunk_count,
        "html_hash": html_hash,
        "status": "cleaned"
    }).eq("id", scrape_id).execute()

def fail_scrape_job(scrape_id: int, error_message: str, status: str = "failed"):
    """Mark a scrape job with a failure status and error message."""
    supabase.table("scrapes").update({
        "status": status,
        "error_message": error_message
    }).eq("id", scrape_id).execute()

def update_scrape_status(scrape_id: int, status: str):
    """Update the status of a scrape job."""
    supabase.table("scrapes").update({
        "status": status
    }).eq("id", scrape_id).execute()

def log_scrape_event(
    scrape_id: int,
    worker: str,
    event_type: str,
    severity: str = "info",
    message: Optional[str] = None,
    metrics: Optional[Dict[str, Any]] = None,
    from_status: Optional[str] = None,
    to_status: Optional[str] = None,
    worker_run_id: Optional[str] = None,
    company_id: Optional[int] = None,
    career_page_id: Optional[int] = None
) -> None:
    """
    Persist one structured scrape event.
    Best-effort only: logging failures must never break worker flow.
    OPTIMIZATION: Pass company_id and career_page_id to avoid an extra DB round-trip.
    """
    try:
        # Resolve IDs if missing
        if company_id is None or career_page_id is None:
            scrape_response = supabase.table("scrapes")\
                .select("career_page_id, career_pages(company_id)")\
                .eq("id", scrape_id)\
                .limit(1)\
                .execute()

            if not scrape_response.data:
                # Scrape ID likely invalid or gone
                return

            scrape_row = scrape_response.data[0]
            fetched_career_page_id = scrape_row.get("career_page_id")
            
            # Prefer passed-in values, fallback to fetched
            if career_page_id is None:
                career_page_id = fetched_career_page_id
                
            if company_id is None:
                career_page = scrape_row.get("career_pages")
                if isinstance(career_page, dict):
                    company_id = career_page.get("company_id")

        payload = {
            "scrape_id": scrape_id,
            "career_page_id": career_page_id,
            "company_id": company_id,
            "worker": worker,
            "event_type": event_type,
            "severity": severity,
            "message": message,
            "metrics": metrics or {}
        }

        if from_status is not None:
            payload["from_status"] = from_status
        if to_status is not None:
            payload["to_status"] = to_status
        if worker_run_id is not None:
            payload["worker_run_id"] = worker_run_id

        supabase.table("scrape_log_events").insert(payload).execute()
    except Exception as e:
        print(f"Warning: failed to persist scrape event for scrape {scrape_id}: {e}")

def get_scrape_dashboard_summary() -> Dict[str, Any]:
    """Read aggregated scrape dashboard metrics for observability UI."""
    response = supabase.table("scrape_dashboard_live_v").select("*").limit(1).execute()
    if response.data:
        return response.data[0]
    return {}

def get_scrape_events(
    scrape_id: Optional[int] = None,
    event_type: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """Read scrape event feed with optional filters."""
    query = supabase.table("scrape_event_feed_v").select("*").order("created_at", desc=True)

    if scrape_id is not None:
        query = query.eq("scrape_id", scrape_id)
    if event_type is not None:
        query = query.eq("event_type", event_type)
    if severity is not None:
        query = query.eq("severity", severity)
    if limit is not None:
        query = query.limit(limit)

    response = query.execute()
    return response.data

from datetime import datetime, timedelta, timezone

def get_latest_scrape_hash(
    career_page_id: int,
    statuses: Optional[List[str]] = None
) -> Optional[str]:
    """Get the most recent non-null html_hash for a career page from trusted statuses."""
    statuses = statuses or ["cleaned", "core_extracted"]

    response = supabase.table("scrapes")\
        .select("html_hash")\
        .eq("career_page_id", career_page_id)\
        .in_("status", statuses)\
        .order("created_at", desc=True)\
        .limit(20)\
        .execute()

    if response.data:
        for row in response.data:
            html_hash = row.get("html_hash")
            if isinstance(html_hash, str) and html_hash.strip():
                return html_hash
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

def get_cleaned_scrapes() -> List[Dict]:
    """Get all scrapes with status 'cleaned'."""
    response = supabase.table("scrapes").select("id, chunks_json, chunk_count, career_pages(company_id)").eq("status", "cleaned").execute()
    return response.data

def insert_jobs(jobs_data: List[Dict]):
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
    candidates = supabase.table("scrapes").select("id, career_page_id, chunks_json, chunk_count, career_pages(company_id, url)")\
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


def fetch_next_scrape_job(stale_extracting_minutes: int = 30) -> Optional[dict]:
    """
    Atomically fetches one scrape job for content extraction.
    Logic:
    1. Finds a 'queued' job.
    2. OR reclaims one stale 'extracting' job by requeueing it.
    3. OR finds a 'core_extracted' job older than 24 hours (recycling it).
    4. Claims selected job as 'extracting' and bumps 'created_at' to now.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    
    # 1. Try 'queued'
    response = supabase.table("scrapes").select("id, career_page_id, career_pages(company_id)")\
        .eq("status", "queued")\
        .limit(1)\
        .execute()
    
    target_id = None
    original_status = None
    
    if response.data:
        target_id = response.data[0]["id"]
        original_status = "queued"
    else:
        # 2. Reclaim stale 'extracting' jobs by moving them back to 'queued'
        stale_extracting_threshold = (
            datetime.now(timezone.utc) - timedelta(minutes=stale_extracting_minutes)
        ).isoformat()

        response = supabase.table("scrapes").select("id, career_page_id, career_pages(company_id)")\
            .eq("status", "extracting")\
            .lt("created_at", stale_extracting_threshold)\
            .limit(1)\
            .execute()

        if response.data:
            stale_id = response.data[0]["id"]
            reclaimed = supabase.table("scrapes").update({"status": "queued"})\
                .eq("id", stale_id)\
                .eq("status", "extracting")\
                .lt("created_at", stale_extracting_threshold)\
                .execute()

            if reclaimed.data:
                target_id = stale_id
                original_status = "queued"
            else:
                target_id = None
                original_status = None

        # 3. Try 'core_extracted' > 24h
        if not target_id:
            threshold = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

            response = supabase.table("scrapes").select("id, career_page_id, career_pages(company_id)")\
                .eq("status", "core_extracted")\
                .lt("created_at", threshold)\
                .limit(1)\
                .execute()

            if response.data:
                target_id = response.data[0]["id"]
                original_status = "core_extracted"

    if target_id:
        # Atomic claim lock for whichever candidate path selected.
        update_payload = {
            "status": "extracting",
            "created_at": now_iso
        }
        
        res = supabase.table("scrapes").update(update_payload)\
            .eq("id", target_id)\
            .eq("status", original_status)\
            .execute()
            
        if res.data:
            # Return the originally fetched candidate data which contains the company_id relation
            # The update response might strictly return attributes of the updated row (scrapes),
            # so we merge the original relation info if needed.
            result = res.data[0]
            # Find the candidate object that matched target_id
            for r in (response.data or []):
                if r["id"] == target_id:
                    result.update(r) # Merge in career_pages(company_id)
                    break
            return result

    return None


def fetch_next_job_content_job(worker_run_id: str) -> Optional[dict]:
    """
    Atomically claims one eligible jobs.url task and locks jobs.content_status as 'job_extracting'.
    Global ATS pacing/caps are enforced in SQL function claim_next_job_page_fetch.
    """
    response = supabase.rpc(
        "claim_next_job_page_fetch",
        {"p_worker_run_id": worker_run_id}
    ).execute()

    if response.data and len(response.data) > 0:
        return response.data[0]
    return None


def complete_job_page_fetch_result(
    fetch_id: int,
    status: str,
    exists_verified: bool = False,
    http_status: Optional[int] = None,
    final_url: Optional[str] = None,
    content_type: Optional[str] = None,
    raw_html: Optional[str] = None,
    markdown: Optional[str] = None,
    html_hash: Optional[str] = None,
    error_message: Optional[str] = None
) -> None:
    """
    Completes a claimed job_page_fetch record and releases ATS in-flight slot.
    Also updates jobs.content_status:
    - extracted -> job_extracted
    - failed/gone/blocked -> open
    """
    supabase.rpc(
        "complete_job_page_fetch",
        {
            "p_fetch_id": fetch_id,
            "p_status": status,
            "p_exists_verified": exists_verified,
            "p_http_status": http_status,
            "p_final_url": final_url,
            "p_content_type": content_type,
            "p_raw_html": raw_html,
            "p_markdown": markdown,
            "p_html_hash": html_hash,
            "p_error_message": error_message
        }
    ).execute()


def get_latest_job_page_hash(job_id: int) -> Optional[str]:
    """Returns the latest extracted html_hash for one job URL fetch."""
    response = supabase.table("job_page_fetches")\
        .select("html_hash")\
        .eq("job_id", job_id)\
        .eq("status", "extracted")\
        .order("updated_at", desc=True)\
        .limit(5)\
        .execute()

    if response.data:
        for row in response.data:
            html_hash = row.get("html_hash")
            if isinstance(html_hash, str) and html_hash.strip():
                return html_hash
    return None

def get_job_raw_scrape_id(job_id: int) -> Optional[int]:
    """Get the raw_scrape_id for a given job_id."""
    response = supabase.table("jobs").select("raw_scrape_id").eq("id", job_id).limit(1).execute()
    if response.data:
        return response.data[0].get("raw_scrape_id")
    return None

def fetch_next_description_extraction_job() -> Optional[dict]:
    """
    Atomically fetches one 'extracted' job_page_fetches record with markdown,
    marks it as 'description_extracting', and returns it.
    """
    candidates = supabase.table("job_page_fetches").select("id, job_id, markdown")\
        .eq("status", "extracted")\
        .limit(10)\
        .execute()

    if not candidates.data:
        return None
        
    candidate = None
    for r in candidates.data:
        if r.get("markdown"):
            candidate = r
            break
            
    if not candidate:
        return None
    
    fetch_id = candidate["id"]
    
    # Attempt optimistic lock
    response = supabase.table("job_page_fetches").update({"status": "description_extracting"})\
        .eq("id", fetch_id)\
        .eq("status", "extracted")\
        .execute()
    
    if len(response.data) > 0:
        return candidate
    
    return None

def update_job_page_fetch_status(fetch_id: int, status: str, error_message: Optional[str] = None):
    """Updates the status of a job_page_fetches record."""
    payload = {"status": status}
    if error_message is not None:
        payload["error_message"] = error_message
    supabase.table("job_page_fetches").update(payload).eq("id", fetch_id).execute()

def insert_job_description(job_id: int, ai_data: dict):
    """Upserts the AI-extracted job description into the job_descriptions table."""
    def parse_bool(val):
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            val_lower = val.lower()
            if val_lower in ("true", "yes", "1"):
                return True
            if val_lower in ("false", "no", "0"):
                return False
        return None

    is_entry_level = parse_bool(ai_data.get("is_entry_level"))
    internship = parse_bool(ai_data.get("internship"))
    visa_sponsorship = parse_bool(ai_data.get("visa_sponsorship"))
    degree_required = parse_bool(ai_data.get("degree_required"))

    payload = {
        "job_id": job_id,
        "summary": ai_data.get("summary"),
        "responsibilities": ai_data.get("responsibilities", []),
        "requirements": ai_data.get("requirements", []),
        "preferred_requirements": ai_data.get("preferred_requirements", []),
        "tech_stack": ai_data.get("tech_stack", []),
        "experience_level": ai_data.get("experience_level"),
        "is_entry_level": is_entry_level,
        "years_experience_min": ai_data.get("years_experience", {}).get("min") if isinstance(ai_data.get("years_experience"), dict) else None,
        "years_experience_max": ai_data.get("years_experience", {}).get("max") if isinstance(ai_data.get("years_experience"), dict) else None,
        "employment_type": ai_data.get("employment_type"),
        "internship": internship,
        "salary_min": ai_data.get("salary_range", {}).get("min") if isinstance(ai_data.get("salary_range"), dict) else None,
        "salary_max": ai_data.get("salary_range", {}).get("max") if isinstance(ai_data.get("salary_range"), dict) else None,
        "salary_currency": ai_data.get("salary_range", {}).get("currency") if isinstance(ai_data.get("salary_range"), dict) else None,
        "visa_sponsorship": visa_sponsorship,
        "remote_policy": ai_data.get("remote_policy"),
        "team": ai_data.get("team"),
        "degree_required": degree_required
    }
    
    supabase.table("job_descriptions").upsert(payload).execute()
