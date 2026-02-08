import time
from database.database import get_cleaned_scrapes, insert_jobs, update_scrape_status, fetch_next_ready_job, fail_scrape_job
from database.AI_connection.AI import extract_jobs_from_chunk
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
            # If it's a relative path (starts with /), join with base domain
            if raw_url.startswith("/"):
                # Use urllib to join base_url and relative path
                # "https://example.com/careers" + "/jobs/123" -> "https://example.com/jobs/123"
                job_url = urllib.parse.urljoin(base_url, raw_url)
            else:
                job_url = raw_url

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

def process_scrape(scrape):
    scrape_id = scrape.get("id")
    chunk_count = scrape.get("chunk_count")
    chunks = scrape.get("chunks_json")
    
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
    
    all_jobs = []
    
    if isinstance(chunks, list):
        for i, chunk in enumerate(chunks):
            print(f"  Extracting from chunk {i+1}/{len(chunks)}...")
            job_listings = extract_jobs_from_chunk(chunk)
            if job_listings:
                all_jobs.extend(job_listings)
    
    # Clean jobs
    cleaned_jobs, errors = clean_jobs(all_jobs, company_id, scrape_id, career_page_url)
    
    print(f"  Extracted {len(all_jobs)} raw jobs.")
    print(f"  Cleaned {len(cleaned_jobs)} valid jobs.")
    
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

def extract_jobs():
    print("Starting job extraction worker...")
    
    while True:
        try:
            scrape = fetch_next_ready_job()

            if not scrape:
                # No jobs ready, wait a bit
                time.sleep(5)
                continue
            
            # We have a lock on this scrape now, processing...
            try:
                process_scrape(scrape)
                
                # Success
                update_scrape_status(scrape.get("id"), "core_extracted")
                print(f"  Updated scrape {scrape.get('id')} status to 'core_extracted'.")
                
            except Exception as e:
                print(f"  Error processing scrape {scrape.get('id')}: {e}")
                fail_scrape_job(scrape.get("id"), str(e))
                print(f"  Updated scrape {scrape.get('id')} status to 'failed'.")
                
        except Exception as e:
            # Global loop error handler to prevent crashing
            print(f"Unexpected global error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    extract_jobs()
