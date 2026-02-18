from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from markdownify import markdownify as md
import time
import re
import json
import hashlib
from database.database import get_career_page_url, get_career_pages, create_scrape_job, update_scrape_job, fail_scrape_job, get_latest_scrape_hash, is_recently_scraped, fetch_next_scrape_job, update_scrape_status, log_scrape_event

REMOVE_TAGS = [
    "script", "style", "noscript",
    "svg", "canvas", "iframe",
    "header", "footer", "nav"
]

def chunk_text(text, size=3000, overlap=400):
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        start = end - overlap
        # Prevent infinite loop if overlap >= size, though default values avoid this
        if start >= end:
            start = end
    return chunks

def remove_artifacts(text):
    # remove long runs of symbols
    text = re.sub(r'[%=*+]{5,}', '', text)
    
    # remove excessive blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()

def normalize(text):
    text = remove_artifacts(text)
    # Collapse multiple spaces/tabs to single space
    text = re.sub(r'[ \t]+', ' ', text)
    return text.strip()

def clean_html(html):
    soup = BeautifulSoup(html, "lxml")
    for tag in REMOVE_TAGS:
        for element in soup.find_all(tag):
            element.decompose()
    return str(soup)


def process_scrape_job(scrape_job):
    scrape_id = scrape_job["id"]
    career_page_id = scrape_job["career_page_id"]
    
    print(f"Processing Scrape ID: {scrape_id} for Career Page ID: {career_page_id}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
             user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        page = context.new_page()
        
        try:
            url = get_career_page_url(career_page_id)
            print(f"Navigating to {url}...")
            log_scrape_event(
                scrape_id=scrape_id,
                worker="site_content_worker",
                event_type="url_hit",
                metrics={"url": url}
            )
            
            page.goto(url)
            page.wait_for_load_state("networkidle")
            time.sleep(5) 
            
            html_content = page.content()
            html_hash = hashlib.md5(html_content.encode('utf-8')).hexdigest()
            print(f"Content Hash: {html_hash}")

            # Check for duplicate ONLY if we care about skipping unchanged content. 
            # But here we already locked the job. If it IS standard practice to skip, 
            # we should still mark it as 'cleaned' but maybe with a note or just regular update?
            # User logic from before: "Content unchanged... Skipping processing."
            # If we skip, we should still mark it as 'cleaned' so it doesn't get picked up again as 'failed' or stuck 'extracting'.
            
            last_hash = get_latest_scrape_hash(career_page_id)
            # Be careful: get_latest_scrape_hash looks for matches. 
            # Since we just updated THIS job to 'extracting', it won't be returned by 'get_latest_scrape_hash' if that function filters by 'cleaned'/'completed'?
            # checking database.py: get_latest_scrape_hash queries "scrapes" ... .neq("html_hash", "null"). 
            # Our current job is 'extracting' and likely has null hash if recycled, or old hash if recycled.
            
            if last_hash and last_hash == html_hash:
                print(f"Content unchanged (Hash match). Setting status to 'core_extracted' and skipping.")
                log_scrape_event(
                    scrape_id=scrape_id,
                    worker="site_content_worker",
                    event_type="heartbeat",
                    message="Content unchanged. Skipping conversion and extraction.",
                    metrics={"outcome": "unchanged_hash_skip"}
                )
                update_scrape_status(scrape_id, "core_extracted")
                return

            print("Page content retrieved. Cleaning HTML...")
            cleaned_html = clean_html(html_content)
            
            print("Converting to markdown...")
            markdown_content = md(cleaned_html, strip=['img'])
            
            if markdown_content:
                print("Normalizing markdown content...")
                markdown_content = normalize(markdown_content)
                
                print("Chunking content...")
                chunks = chunk_text(markdown_content)
                log_scrape_event(
                    scrape_id=scrape_id,
                    worker="site_content_worker",
                    event_type="chunk_progress",
                    message="Content chunking completed.",
                    metrics={
                        "chunk_index": len(chunks),
                        "chunk_total": len(chunks),
                        "conversion": "markdown_success"
                    }
                )
                
                print("Updating scrape job in database...")
                update_scrape_job(
                    scrape_id=scrape_id,
                    raw_html=cleaned_html,
                    markdown=markdown_content,
                    chunks=chunks,
                    chunk_count=len(chunks),
                    html_hash=html_hash
                )
                print("Scrape job completed successfully.")
            else:
                print("Failed to convert content.")
                log_scrape_event(
                    scrape_id=scrape_id,
                    worker="site_content_worker",
                    event_type="scrape_failed",
                    severity="error",
                    message="Failed to convert content to markdown",
                    metrics={"error_message": "Failed to convert content to markdown"}
                )
                fail_scrape_job(scrape_id, "Failed to convert content to markdown")
                
        except Exception as e:
            print(f"An error occurred: {e}")
            log_scrape_event(
                scrape_id=scrape_id,
                worker="site_content_worker",
                event_type="scrape_failed",
                severity="error",
                message=f"An error occurred: {e}",
                metrics={"error_message": str(e)}
            )
            fail_scrape_job(scrape_id, str(e))
        finally:
            browser.close()

def run_worker():
    print("Starting site content extraction worker...")
    while True:
        job = None
        try:
            job = fetch_next_scrape_job()
            if not job:
                print("No jobs ready. Sleeping 7s...")
                time.sleep(7)
                continue
            
            process_scrape_job(job)
            
        except Exception as e:
            print(f"Global worker error: {e}")
            if job and job.get("id"):
                log_scrape_event(
                    scrape_id=job.get("id"),
                    worker="site_content_worker",
                    event_type="worker_error",
                    severity="error",
                    message=f"Global worker error: {e}",
                    metrics={"error_message": str(e)}
                )
            time.sleep(7)

if __name__ == "__main__":
    run_worker()
