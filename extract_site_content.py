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

def process_scrape_job(scrape_job, browser):
    scrape_id = scrape_job["id"]
    career_page_id = scrape_job["career_page_id"]
    context = None

    print(f"Processing Scrape ID: {scrape_id} for Career Page ID: {career_page_id}")

    try:
        url = get_career_page_url(career_page_id)
        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()

        print(f"Navigating to {url}...")
        html_content, wait_mode = navigate_and_capture_html(page, url)

        log_scrape_event(
            scrape_id=scrape_id,
            worker="site_content_worker",
            event_type="url_hit",
            metrics={"url": url, "wait_mode": wait_mode}
        )

        html_hash = hashlib.md5(html_content.encode('utf-8')).hexdigest()
        print(f"Content Hash: {html_hash}")

        last_hash = get_latest_scrape_hash(
            career_page_id,
            statuses=["cleaned", "core_extracted"]
        )
        hash_match = bool(last_hash and last_hash == html_hash)

        log_scrape_event(
            scrape_id=scrape_id,
            worker="site_content_worker",
            event_type="heartbeat",
            metrics={
                "last_hash_present": bool(last_hash),
                "hash_match": hash_match,
                "wait_mode": wait_mode
            }
        )

        if hash_match:
            print("Content unchanged (Hash match). Setting status to 'core_extracted' and skipping.")
            log_scrape_event(
                scrape_id=scrape_id,
                worker="site_content_worker",
                event_type="heartbeat",
                message="Content unchanged. Skipping conversion and extraction.",
                metrics={"outcome": "unchanged_hash_skip", "wait_mode": wait_mode}
            )
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
            log_scrape_event(
                scrape_id=scrape_id,
                worker="site_content_worker",
                event_type="chunking_completed",
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
            worker="site_content_worker",
            event_type="scrape_failed",
            severity="error",
            message="Failed to convert content to markdown",
            metrics={"error_message": "Failed to convert content to markdown"}
        )
        fail_scrape_job(scrape_id, "Failed to convert content to markdown")
        return False

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
        return is_fatal_browser_error(e)
    finally:
        if context:
            try:
                context.close()
            except Exception:
                pass

def run_worker():
    print("Starting site content extraction worker...")
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

                restart_browser = process_scrape_job(job, browser)
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
