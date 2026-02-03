
from database.database import get_cleaned_scrapes, insert_jobs, update_scrape_status
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

def valid_job_url(url, avg_len):
    if not url:
        return False

    url = url.strip()

    # must be real or relative URL
    if not (url.startswith("http") or url.startswith("/")):
        return False

    # no spaces inside (real URLs never contain raw spaces)
    if " " in url:
        return False

    # Round up (ceil) to nearest int
    MIN_LEN = math.ceil(avg_len * 0.75)
    MAX_LEN = math.ceil(avg_len * 1.5)

    if len(url) < MIN_LEN or len(url) > MAX_LEN:
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

def clean_jobs(ai_results, company_id, scrape_id):
    cleaned = []
    error_messages = []
    seen = set()

    current_time = datetime.now(timezone.utc).isoformat()
    
    # Pre-process: Unwrap markdown URLs
    for job in ai_results:
        if isinstance(job, dict) and job.get("job_url") and isinstance(job["job_url"], str):
             job["job_url"] = unwrap_markdown_url(job["job_url"].strip())

    # Calculate average URL length for this batch
    valid_urls_lens = []
    for job in ai_results:
        if isinstance(job, dict) and job.get("job_url") and isinstance(job["job_url"], str):
             valid_urls_lens.append(len(job["job_url"].strip()))
    
    if valid_urls_lens:
        avg_len = sum(valid_urls_lens) / len(valid_urls_lens)
    else:
        avg_len = 0

    for job in ai_results:
        try:
            if not isinstance(job, dict):
                 error_messages.append(f"Skipping job: Invalid format (not a dict). Data: {job}")
                 continue
                 
            if not job.get("title") or not job.get("job_url"):
                error_messages.append(f"Skipping job: Missing title or url. Data provided: {job}")
                continue

            if not valid_job_url(job["job_url"], avg_len):
                 error_messages.append(f"Skipping job: Invalid URL (validation failed). URL: {job['job_url']} (Avg Len: {avg_len:.1f})")
                 continue

            key = (company_id, job["job_url"])
            if key in seen:
                error_messages.append(f"Skipping job: Duplicate in batch. URL: {job['job_url']}")
                continue
            seen.add(key)

            # First clean markdown links from title, then normalize
            raw_title = clean_title(job["title"])
            job_title = normalize_title(raw_title)
            
            if not job_title:
                 error_messages.append(f"Skipping job: Title became empty after normalization. Original: {job['title']}")
                 continue

            job_url = job["job_url"].strip()
            
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

def extract_jobs():
    print("Fetching cleaned scrapes from database...")
    scrapes = get_cleaned_scrapes()
    
    if not scrapes:
        print("No cleaned scrapes found.")
        return

    print(f"Found {len(scrapes)} cleaned scrapes.")

    for scrape in scrapes[1:]: # Testing with 1 scrape as per previous edit
        scrape_id = scrape.get("id")
        chunk_count = scrape.get("chunk_count")
        chunks = scrape.get("chunks_json")
        
        try:
            # Get company_id safe access
            career_pages = scrape.get("career_pages") or {}
            company_id = career_pages.get("company_id")
            
            if not company_id:
                print(f"Skipping scrape {scrape_id}: Missing company_id.")
                continue

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
            cleaned_jobs, errors = clean_jobs(all_jobs, company_id, scrape_id)
            
            print(f"  Extracted {len(all_jobs)} raw jobs.")
            print(f"  Cleaned {len(cleaned_jobs)} valid jobs.")
            
            if errors:
                print(f"  Encountered {len(errors)} errors/skips. errors: {errors}\n\n\n\n")

            if cleaned_jobs:
                print(f"  Upserting {len(cleaned_jobs)} jobs to database...")
                try:
                    inserted_data = insert_jobs(cleaned_jobs)
                    
                    # Calculate stats
                    new_count = 0
                    updated_count = 0
                    
                    # Heuristic: If first_seen_at is close to now, it's new. 
                    # Otherwise it's updated.
                    # However, comparing string timestamps can be tricky.
                    # Let's rely on string equality of first_seen_at vs last_seen_at (approximately) if created now.
                    # Actually, easier: if first_seen_at != last_seen_at, it's definitely updated (since we just updated last_seen_at to NOW).
                    # If first_seen_at == last_seen_at, it's likely new (created just now).
                    
                    # Note: DB might have slight microsecond diffs if defaults apply differently.
                    # But 'last_seen_at' is what we sent. 'first_seen_at' is default NOW().
                    # Let's check first_seen_at timestamp vs current time logic if they differ significantly.
                    # Actually, if first_seen_at < last_seen_at (by more than a few seconds), it's old.
                    
                    now_ts = datetime.now(timezone.utc)
                    
                    for row in inserted_data:
                        first_seen = row.get("first_seen_at")
                        try:
                            first_seen_dt = datetime.fromisoformat(first_seen)
                            # datetime.fromisoformat handles most ISO strings in recent python
                            
                            delta = (now_ts - first_seen_dt).total_seconds()
                            if delta < 10: # Created within last 10 seconds
                                new_count += 1
                            else:
                                updated_count += 1
                        except Exception:
                            # Fallback if parsing fails, assume updated if unclear
                            updated_count += 1

                    print(f"  Successfully processed jobs.")
                    print(f"  Stats: {new_count} New, {updated_count} Updated (Duplicate URL).")

                    # Update scrape status to core_extracted
                    update_scrape_status(scrape_id, "core_extracted")
                    print(f"  Updated scrape {scrape_id} status to 'core_extracted'.")
                    
                except Exception as e:
                    print(f"  Error inserting jobs: {e}")
        except Exception as e:
            print(f"Skipping scrape {scrape_id} due to unexpected error: {e}")

if __name__ == "__main__":
    extract_jobs()
