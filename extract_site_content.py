from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from markdownify import markdownify as md
import time
import re
import hashlib
from database.database import (
    get_career_page_url,
    update_scrape_job,
    fail_scrape_job,
    get_latest_scrape_hash,
    fetch_next_scrape_job,
    update_scrape_status,
    log_scrape_event
)

NAV_TIMEOUT_MS = 45000
NETWORKIDLE_BUDGET_MS = 7000
SELECTOR_WAIT_MS = 8000
BROWSER_RECYCLE_JOBS = 100
WAIT_SELECTORS = ("main", "[role='main']", "section", "body")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

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

def navigate_and_capture_html(page, url):
    page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
    wait_mode = "domcontentloaded"

    try:
        page.wait_for_load_state("networkidle", timeout=NETWORKIDLE_BUDGET_MS)
        wait_mode = "networkidle"
    except Exception:
        pass

    per_selector_timeout = max(500, SELECTOR_WAIT_MS // len(WAIT_SELECTORS))
    for selector in WAIT_SELECTORS:
        try:
            page.wait_for_selector(selector, timeout=per_selector_timeout)
            wait_mode = f"selector:{selector}"
            break
        except Exception:
            continue

    return page.content(), wait_mode

def launch_browser(playwright):
    return playwright.chromium.launch(headless=True)

def is_fatal_browser_error(error):
    message = str(error).lower()
    fatal_markers = (
        "target page, context or browser has been closed",
        "browser has been closed",
        "connection closed",
        "browser closed"
    )
    return any(marker in message for marker in fatal_markers)

def process_scrape_job(scrape_job, browser, worker_run_id):
    scrape_id = scrape_job["id"]
    career_page_id = scrape_job["career_page_id"]
    career_pages = scrape_job.get("career_pages")
    company_id = career_pages.get("company_id") if isinstance(career_pages, dict) else None
    context = None
    
    start_time = time.time()

    print(f"Processing Scrape ID: {scrape_id} for Career Page ID: {career_page_id}")

    try:
        url = get_career_page_url(career_page_id)
        
        # 1. Fetch Started
        log_scrape_event(
            scrape_id=scrape_id,
            company_id=company_id,
            career_page_id=career_page_id,
            worker="site_content_worker",
            event_type="fetch_started",
            worker_run_id=worker_run_id,
            metrics={"url": url}
        )
        
        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()

        print(f"Navigating to {url}...")
        html_content, wait_mode = navigate_and_capture_html(page, url)
        
        fetch_duration = int((time.time() - start_time) * 1000)

        html_hash = hashlib.md5(html_content.encode('utf-8')).hexdigest()
        print(f"Content Hash: {html_hash}")

        last_hash = get_latest_scrape_hash(
            career_page_id,
            statuses=["cleaned", "core_extracted"]
        )
        hash_match = bool(last_hash and last_hash == html_hash)
        
        # 2. Fetch Finished
        log_scrape_event(
            scrape_id=scrape_id,
            company_id=company_id,
            career_page_id=career_page_id,
            worker="site_content_worker",
            event_type="fetch_finished",
            worker_run_id=worker_run_id,
            metrics={
                "duration_ms": fetch_duration,
                "http_status": 200, # Approximation since navigate_and_capture_html doesn't return status yet, but successful nav implies 200-ish
                "bytes_downloaded": len(html_content),
                "hash_changed": not hash_match,
                "wait_mode": wait_mode
            }
        )

        if hash_match:
            print("Content unchanged (Hash match). Setting status to 'core_extracted' and skipping.")
            # No heartbeat here, just transition status
            update_scrape_status(scrape_id, "core_extracted")
            return False

        print("Page content retrieved. Cleaning HTML...")
        cleaned_html = clean_html(html_content)

        print("Converting to markdown...")
        markdown_content = md(cleaned_html, strip=['img'])

        if markdown_content:
            print("Normalizing markdown content...")
            markdown_content = normalize(markdown_content)

            print("Chunking content...")
            chunks = chunk_text(markdown_content)
            
            # 3. Chunking/Process Log
            log_scrape_event(
                scrape_id=scrape_id,
                company_id=company_id,
                career_page_id=career_page_id,
                worker="site_content_worker",
                event_type="chunking_completed",
                worker_run_id=worker_run_id,
                message="Content chunking completed.",
                metrics={
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
            return False

        print("Failed to convert content.")
        log_scrape_event(
            scrape_id=scrape_id,
            company_id=company_id,
            career_page_id=career_page_id,
            worker="site_content_worker",
            event_type="error",
            severity="error",
            worker_run_id=worker_run_id,
            message="Failed to convert content to markdown",
            metrics={"error_type": "markdown_conversion_failed"}
        )
        fail_scrape_job(scrape_id, "Failed to convert content to markdown")
        return False

    except Exception as e:
        print(f"An error occurred: {e}")
        log_scrape_event(
            scrape_id=scrape_id,
            company_id=company_id,
            career_page_id=career_page_id,
            worker="site_content_worker",
            event_type="error",
            severity="error",
            worker_run_id=worker_run_id,
            message=f"An error occurred: {e}",
            metrics={"error_message": str(e), "error_type": "exception"}
        )
        fail_scrape_job(scrape_id, str(e))
        return is_fatal_browser_error(e)
    finally:
        if context:
            try:
                context.close()
            except Exception:
                pass

def run_worker():
    worker_run_id = f"site-content-worker-{int(time.time())}"
    print(f"Starting site content extraction worker. run_id={worker_run_id}")
    
    with sync_playwright() as p:
        browser = launch_browser(p)
        processed_since_launch = 0

        while True:
            job = None
            try:
                job = fetch_next_scrape_job(stale_extracting_minutes=30)
                if not job:
                    print("No jobs ready. Sleeping 7s...")
                    time.sleep(7)
                    continue

                restart_browser = process_scrape_job(job, browser, worker_run_id)
                processed_since_launch += 1

                if restart_browser or processed_since_launch >= BROWSER_RECYCLE_JOBS:
                    reason = "fatal_browser_error" if restart_browser else "recycle_threshold"
                    print(f"Recycling browser due to: {reason}")
                    try:
                        browser.close()
                    except Exception:
                        pass
                    browser = launch_browser(p)
                    processed_since_launch = 0

            except Exception as e:
                print(f"Global worker error: {e}")
                if job and job.get("id"):
                    career_pages = job.get("career_pages")
                    company_id = career_pages.get("company_id") if isinstance(career_pages, dict) else None
                    log_scrape_event(
                        scrape_id=job.get("id"),
                        company_id=company_id,
                        career_page_id=job.get("career_page_id"),
                        worker="site_content_worker",
                        event_type="worker_error",
                        severity="error",
                        worker_run_id=worker_run_id,
                        message=f"Global worker error: {e}",
                        metrics={"error_message": str(e)}
                    )
                time.sleep(7)

if __name__ == "__main__":
    run_worker()
