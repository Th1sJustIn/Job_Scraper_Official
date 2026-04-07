import time
from database.database import get_cleaned_scrapes, insert_jobs, update_scrape_status, fetch_next_ready_job, fail_scrape_job, log_scrape_event
from database.AI_connection.AI import (
    extract_jobs_from_chunk,
    ensure_llm_server_available,
    LLMConnectionError,
)
import json
import hashlib

import re
from datetime import datetime, timezone

def normalize_title(title):
    t = title.strip()

    # remove wrapping pairs if the ENTIRE string is wrapped
    # We want to turn "[Senior Product Manager, Payments]" -> "Senior Product Manager, Payments"
    # But preserve "[NYC] Software Engineer"
    
    if t.startswith("[") and t.endswith("]"):
        t = t[1:-1].strip()
    elif t.startswith("(") and t.endswith(")"):
        t = t[1:-1].strip()

    return " ".join(t.split())

import math

def valid_job_url(url):
    if not url:
        return False

    url = url.strip()

    # must be real or relative URL
    if not (url.startswith("http") or url.startswith("/")):
        return False

    # no spaces inside (real URLs never contain raw spaces)
    if " " in url:
        return False

   
    return True

def unwrap_markdown_url(url):
    # Matches [Link Text](URL)
    match = re.match(r"\[.*?\]\((.*?)\)", url)
    return match.group(1) if match else url

def generate_job_hash(title, url):
    content = f"{title}{url}"
    return hashlib.md5(content.encode('utf-8')).hexdigest()

def clean_title(title):
    if not title:
        return title

    # If title is markdown link: [Title](url) -> Title
    match = re.match(r"\[(.*?)\]\(.*?\)", title)
    if match:
        return match.group(1).strip()

    return title.strip()

import urllib.parse

def clean_jobs(ai_results, company_id, scrape_id, base_url):
    cleaned = []
    error_messages = []
    seen = set()

    current_time = datetime.now(timezone.utc).isoformat()
    
    # Pre-process: Unwrap markdown URLs
    for job in ai_results:
        if isinstance(job, dict) and job.get("job_url") and isinstance(job["job_url"], str):
             job["job_url"] = unwrap_markdown_url(job["job_url"].strip())

    for job in ai_results:
        try:
            if not isinstance(job, dict):
                 error_messages.append(f"Skipping job: Invalid format (not a dict). Data: {job}")
                 continue
                 
            if not job.get("title") or not job.get("job_url"):
                error_messages.append(f"Skipping job: Missing title or url. Data provided: {job}")
                continue

            # Normalize URL if relative
            raw_url = job["job_url"].strip()

            # Normalize URL if relative
            raw_url = job["job_url"].strip()

            if raw_url.startswith("http"):
                job_url = raw_url
            elif raw_url.startswith("/"):
                # Root relative path (e.g. "/jobs/123")
                job_url = urllib.parse.urljoin(base_url, raw_url)
            else:
                # STRICT PREFIX VALIDATION
                # We only allow relative URLs that look like valid job paths.
                # Allowed prefixes: /, ?, job, jobs, opening, openings
                lower_url = raw_url.lower()
                allowed_prefixes = ("/", "?", "job", "jobs", "opening", "openings")
                
                if not lower_url.startswith(allowed_prefixes):
                     error_messages.append(f"Skipping job: Invalid relative URL prefix. Must start with {allowed_prefixes}. URL: {raw_url}")
                     continue

                # Ensure base_url has trailing slash so we append to the current path instead of replacing it
                # Logic:
                # If starts with '/', urljoin ignores base path (standard behavior) -> GOOD
                # If starts with 'job...', we want to append, so base must end with '/' -> GOOD
                base_to_use = base_url if base_url.endswith("/") else base_url + "/"
                job_url = urllib.parse.urljoin(base_to_use, raw_url)

            if not valid_job_url(job_url):
                 error_messages.append(f"Skipping job: Invalid URL (validation failed). URL: {job_url}")
                 continue

            key = (company_id, job_url)
            if key in seen:
                error_messages.append(f"Skipping job: Duplicate in batch. URL: {job_url}")
                continue
            seen.add(key)

            # First clean markdown links from title, then normalize
            raw_title = clean_title(job["title"])
            job_title = normalize_title(raw_title)
            
            if not job_title:
                 error_messages.append(f"Skipping job: Title became empty after normalization. Original: {job['title']}")
                 continue
            
            if isinstance(job.get("location"), list):
                location = ", ".join([str(l) for l in job["location"] if l]).strip()
            else:
                location = (job.get("location") or "").strip()

            if isinstance(job.get("department"), list):
                department = ", ".join([str(d) for d in job["department"] if d]).strip()
            else:
                department = (job.get("department") or "").strip()

            # Prepare DB Record
            cleaned.append({
                "company_id": company_id,
                "title": job_title,
                "location": location,
                "department": department,
                "url": job_url,
                "content_hash": generate_job_hash(job_title, job_url),
                "raw_scrape_id": scrape_id,
                "status": "open",
                "last_seen_at": current_time
            })
        except Exception as e:
            error_messages.append(f"Skipping job: Error processing job data. Error: {e}. Data: {job}")

    
    return cleaned, error_messages

def process_scrape(scrape, worker_run_id):
    scrape_id = scrape.get("id")
    chunk_count = scrape.get("chunk_count")
    chunks = scrape.get("chunks_json")
    
    career_page_id = scrape.get("career_page_id")
    # Get company_id safe access
    career_pages = scrape.get("career_pages") or {}
    company_id = career_pages.get("company_id")
    career_page_url = career_pages.get("url")
    
    if not company_id:
        raise ValueError(f"Missing company_id for scrape {scrape_id}")
        
    if not career_page_url:
        print(f"Warning: career_page_url missing for scrape {scrape_id}. Relative URLs may fail.")

    print(f"\nProcessing Scrape ID: {scrape_id} (Company ID: {company_id})")
    print(f"Chunk Count: {chunk_count}")

    ensure_llm_server_available()
    
    all_jobs = []
    
    if isinstance(chunks, list):
        for i, chunk in enumerate(chunks):
            print(f"  Extracting from chunk {i+1}/{len(chunks)}...")
            
            # AI Extraction Step
            ai_start = time.time()
            job_listings = extract_jobs_from_chunk(chunk)
            ai_duration = int((time.time() - ai_start) * 1000)
            
            # Log AI Extraction
            log_scrape_event(
                scrape_id=scrape_id,
                company_id=company_id,
                career_page_id=career_page_id,
                worker="core_extraction_worker",
                event_type="ai_extraction_finished",
                worker_run_id=worker_run_id,
                metrics={
                    "duration_ms": ai_duration,
                    "chunk_index": i + 1,
                    "chunk_total": len(chunks),
                    "jobs_found": len(job_listings) if job_listings else 0,
                    "model": "gemini-2.0-flash", # Hardcoded for now as per system
                    "json_valid": bool(job_listings is not None)
                }
            )
            
            if job_listings:
                all_jobs.extend(job_listings)
    
    # Clean jobs
    cleaned_jobs, errors = clean_jobs(all_jobs, company_id, scrape_id, career_page_url)
    
    print(f"  Extracted {len(all_jobs)} raw jobs.")
    print(f"  Cleaned {len(cleaned_jobs)} valid jobs.")
    
    # Keeping jobs_extracted as a summary event
    log_scrape_event(
        scrape_id=scrape_id,
        company_id=company_id,
        career_page_id=career_page_id,
        worker="core_extraction_worker",
        event_type="jobs_extracted",
        worker_run_id=worker_run_id,
        metrics={
            "jobs_raw": len(all_jobs),
            "jobs_cleaned": len(cleaned_jobs),
            "error_count": len(errors)
        }
    )
    
    if errors:
        print(f"  Encountered {len(errors)} errors/skips. errors: {errors}\n")

    if cleaned_jobs:
        print(f"  Upserting {len(cleaned_jobs)} jobs to database...")
        inserted_data = insert_jobs(cleaned_jobs)
        
        # Calculate stats
        new_count = 0
        updated_count = 0
        
        now_ts = datetime.now(timezone.utc)
        
        if inserted_data:
            for row in inserted_data:
                first_seen = row.get("first_seen_at")
                try:
                    first_seen_dt = datetime.fromisoformat(first_seen)
                    delta = (now_ts - first_seen_dt).total_seconds()
                    if delta < 10: # Created within last 10 seconds
                        new_count += 1
                    else:
                        updated_count += 1
                except Exception:
                    updated_count += 1

        print(f"  Successfully processed jobs.")
        print(f"  Stats: {new_count} New, {updated_count} Updated.")
        log_scrape_event(
            scrape_id=scrape_id,
            company_id=company_id,
            career_page_id=career_page_id,
            worker="core_extraction_worker",
            event_type="jobs_upserted",
            worker_run_id=worker_run_id,
            metrics={
                "new_jobs": new_count,
                "updated_jobs": updated_count
            }
        )

def extract_jobs():
    worker_run_id = f"core-extraction-worker-{int(time.time())}"
    print(f"Starting job extraction worker. run_id={worker_run_id}")
    
    while True:
        scrape = None
        try:
            scrape = fetch_next_ready_job()

            if not scrape:
                # No jobs ready, wait a bit
                print("No jobs ready for core extraction. Sleeping for 5 seconds...")
                time.sleep(5)
                continue
            
            # We have a lock on this scrape now, processing...
            try:
                process_scrape(scrape, worker_run_id)
                
                # Success
                update_scrape_status(scrape.get("id"), "core_extracted")
                print(f"  Updated scrape {scrape.get('id')} status to 'core_extracted'.")

            except LLMConnectionError as e:
                print(f"  Error processing scrape {scrape.get('id')}: {e}")
                log_scrape_event(
                    scrape_id=scrape.get("id"),
                    company_id=scrape.get("career_pages", {}).get("company_id"),
                    career_page_id=scrape.get("career_page_id"),
                    worker="core_extraction_worker",
                    event_type="scrape_failed",
                    severity="error",
                    worker_run_id=worker_run_id,
                    message=f"LLM connection error: {e}",
                    metrics={"error_message": str(e), "error_type": "llm_connection"}
                )
                fail_scrape_job(scrape.get("id"), str(e), status="core_extraction_failed")
                print(f"  Updated scrape {scrape.get('id')} status to 'core_extraction_failed'.")
                print("  LLM check failed. Sleeping 60 seconds before next run.")
                time.sleep(60)

            except Exception as e:
                print(f"  Error processing scrape {scrape.get('id')}: {e}")
                log_scrape_event(
                    scrape_id=scrape.get("id"),
                    company_id=scrape.get("career_pages", {}).get("company_id"),
                    career_page_id=scrape.get("career_page_id"),
                    worker="core_extraction_worker",
                    event_type="scrape_failed",
                    severity="error",
                    worker_run_id=worker_run_id,
                    message=f"Error processing scrape: {e}",
                    metrics={"error_message": str(e), "error_type": "exception"}
                )
                fail_scrape_job(scrape.get("id"), str(e), status="core_extraction_failed")
                print(f"  Updated scrape {scrape.get('id')} status to 'core_extraction_failed'.")
                
        except Exception as e:
            # Global loop error handler to prevent crashing
            print(f"Unexpected global error: {e}")
            if scrape and scrape.get("id"):
                career_pages = scrape.get("career_pages")
                company_id = career_pages.get("company_id") if isinstance(career_pages, dict) else None
                log_scrape_event(
                    scrape_id=scrape.get("id"),
                    company_id=company_id,
                    career_page_id=scrape.get("career_page_id"),
                    worker="core_extraction_worker",
                    event_type="worker_error",
                    severity="error",
                    worker_run_id=worker_run_id,
                    message=f"Unexpected global error: {e}",
                    metrics={"error_message": str(e)}
                )
            time.sleep(5)

if __name__ == "__main__":
    extract_jobs()
