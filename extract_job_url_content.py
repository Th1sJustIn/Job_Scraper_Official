from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from markdownify import markdownify as md
import time
import re
import hashlib
from database.database import (
    fetch_next_job_content_job,
    complete_job_page_fetch_result,
    get_latest_job_page_hash,
    log_scrape_event,
    get_job_raw_scrape_id,
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
POLL_SLEEP_SECONDS = 7

REMOVE_TAGS = [
    "script", "style", "noscript",
    "svg", "canvas", "iframe",
    "header", "footer", "nav"
]


def remove_artifacts(text):
    text = re.sub(r"[%=*+]{5,}", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize(text):
    text = remove_artifacts(text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def clean_html(html):
    soup = BeautifulSoup(html, "lxml")
    for tag in REMOVE_TAGS:
        for element in soup.find_all(tag):
            element.decompose()
    
    # Remove specific unwanted elements
    for element in soup.select(".iti__country-list"):
        element.decompose()
        
    return str(soup)


def navigate_and_capture(page, url):
    response = page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
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

    html_content = page.content()
    status_code = response.status if response else None
    content_type = (response.header_value("content-type") if response else None) or ""
    final_url = page.url
    return html_content, status_code, content_type, final_url, wait_mode


def looks_like_html(content_type, html):
    ct = (content_type or "").lower()
    if "text/html" in ct or "application/xhtml+xml" in ct:
        return True

    probe = (html or "").lstrip().lower()
    return probe.startswith("<!doctype html") or probe.startswith("<html") or "<html" in probe[:500]


def is_blocked(status_code, html):
    if status_code in (403, 429):
        return True

    lowered = (html or "").lower()
    markers = (
        "attention required",
        "access denied",
        "robot check",
        "verify you are human",
        "security check"
    )
    return any(marker in lowered for marker in markers)


def launch_browser(playwright):
    return playwright.chromium.launch(headless=True)


def is_fatal_browser_error(error):
    message = str(error).lower()
    fatal_markers = (
        "target page, context or browser has been closed",
        "browser has been closed",
        "connection closed",
        "browser closed",
    )
    return any(marker in message for marker in fatal_markers)


def process_job_content(claim, browser, worker_run_id):
    fetch_id = claim["fetch_id"]
    job_id = claim["job_id"]
    job_url = claim["job_url"]
    provider_bucket = claim["provider_bucket"]
    context = None
    
    start_time = time.time()

    print(f"Processing fetch_id={fetch_id}, job_id={job_id}, provider={provider_bucket}")

    scrape_id = get_job_raw_scrape_id(job_id)
    if not scrape_id:
        print(f"Warning: could not find raw_scrape_id for job_id={job_id}")

    try:
        # 1. Start Logging
        if scrape_id:
            log_scrape_event(
                scrape_id=scrape_id,
                worker="site_content_worker",
                event_type="fetch_started",
                worker_run_id=worker_run_id,
                metrics={
                    "fetch_id": fetch_id,
                    "job_id": job_id,
                    "url": job_url,
                    "provider": provider_bucket,
                    "attempt": 1 # We'd need to thread attempt count if we want strict accuracy, but 1 is fine for now
                }
            )

        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()

        html_content, status_code, content_type, final_url, wait_mode = navigate_and_capture(page, job_url)
        duration_ms = int((time.time() - start_time) * 1000)
        
        print(f"Hit {job_url} -> status={status_code}, wait={wait_mode}, duration={duration_ms}ms")

        # 2. Network Error / Non-200 Logging
        if not status_code or status_code < 200 or status_code >= 300:
            completion_status = "gone" if status_code in (404, 410) else "blocked" if is_blocked(status_code, html_content) else "failed"
            error_msg = f"Non-2xx response: {status_code}"
            
            if scrape_id:
                log_scrape_event(
                    scrape_id=scrape_id,
                    worker="site_content_worker",
                    event_type="error",
                    severity="error",
                    worker_run_id=worker_run_id,
                    message=error_msg,
                    metrics={
                        "stage": "fetch",
                        "error_type": "http_status",
                        "status_code": status_code,
                        "provider": provider_bucket,
                        "duration_ms": duration_ms
                    }
                )

            complete_job_page_fetch_result(
                fetch_id=fetch_id,
                status=completion_status,
                exists_verified=False,
                http_status=status_code,
                final_url=final_url,
                content_type=content_type,
                error_message=error_msg,
            )
            return False

        if not looks_like_html(content_type, html_content):
            error_msg = "Response did not look like HTML"
            if scrape_id:
                log_scrape_event(
                    scrape_id=scrape_id,
                    worker="site_content_worker",
                    event_type="error",
                    severity="error",
                    worker_run_id=worker_run_id,
                    message=error_msg,
                    metrics={
                        "stage": "validation",
                        "error_type": "invalid_content_type",
                        "content_type": content_type,
                        "provider": provider_bucket,
                        "duration_ms": duration_ms
                    }
                )

            complete_job_page_fetch_result(
                fetch_id=fetch_id,
                status="failed",
                exists_verified=False,
                http_status=status_code,
                final_url=final_url,
                content_type=content_type,
                error_message=error_msg,
            )
            return False

        if is_blocked(status_code, html_content):
            error_msg = "Blocked or anti-bot challenge detected"
            if scrape_id:
                log_scrape_event(
                    scrape_id=scrape_id,
                    worker="site_content_worker",
                    event_type="error",
                    severity="warning",
                    worker_run_id=worker_run_id,
                    message=error_msg,
                    metrics={
                        "stage": "fetch",
                        "error_type": "blocked",
                        "status_code": status_code,
                        "provider": provider_bucket,
                        "duration_ms": duration_ms
                    }
                )

            complete_job_page_fetch_result(
                fetch_id=fetch_id,
                status="blocked",
                exists_verified=False,
                http_status=status_code,
                final_url=final_url,
                content_type=content_type,
                error_message=error_msg,
            )
            return False

        cleaned_html = clean_html(html_content)
        html_hash = hashlib.md5(cleaned_html.encode("utf-8")).hexdigest()
        last_hash = get_latest_job_page_hash(job_id)
        hash_changed = (last_hash != html_hash)
        
        bytes_downloaded = len(html_content)

        # 3. Successful Fetch Log
        if scrape_id:
            log_scrape_event(
                scrape_id=scrape_id,
                worker="site_content_worker",
                event_type="fetch_finished",
                worker_run_id=worker_run_id,
                metrics={
                    "duration_ms": duration_ms,
                    "http_status": status_code,
                    "bytes_downloaded": bytes_downloaded,
                    "hash_changed": hash_changed,
                    "provider": provider_bucket,
                    "fetch_id": fetch_id
                }
            )

        if not hash_changed:
             # Already extracted this exact content
            complete_job_page_fetch_result(
                fetch_id=fetch_id,
                status="extracted",
                exists_verified=True,
                http_status=status_code,
                final_url=final_url,
                content_type=content_type,
                raw_html=cleaned_html,
                markdown="",
                html_hash=html_hash,
            )
            return False

        # Conversion
        conversion_start = time.time()
        markdown_content = md(cleaned_html, strip=["img"])
        markdown_content = normalize(markdown_content) if markdown_content else ""
        conversion_duration = int((time.time() - conversion_start) * 1000)

        # 4. Extraction Log (replacing 'updated')
        if scrape_id:
            log_scrape_event(
                scrape_id=scrape_id,
                worker="site_content_worker",
                event_type="job_description_extracted",
                worker_run_id=worker_run_id,
                metrics={
                    "duration_ms": conversion_duration,
                    "content_length": len(markdown_content),
                    "provider": provider_bucket,
                    "fetch_id": fetch_id
                }
            )

        complete_job_page_fetch_result(
            fetch_id=fetch_id,
            status="extracted",
            exists_verified=True,
            http_status=status_code,
            final_url=final_url,
            content_type=content_type,
            raw_html=cleaned_html,
            markdown=markdown_content,
            html_hash=html_hash,
        )
        return False

    except Exception as e:
        print(f"Error for fetch_id={fetch_id}: {e}")
        
        if scrape_id:
            try:
                log_scrape_event(
                    scrape_id=scrape_id,
                    worker="site_content_worker",
                    event_type="error",
                    severity="error",
                    worker_run_id=worker_run_id,
                    message=f"Exception during content fetch: {e}",
                    metrics={
                        "stage": "unknown",
                        "error_type": "exception",
                        "error_message": str(e),
                        "provider": provider_bucket
                    }
                )
            except Exception:
                pass

        complete_job_page_fetch_result(
            fetch_id=fetch_id,
            status="failed",
            exists_verified=False,
            error_message=str(e),
        )
        return is_fatal_browser_error(e)
    finally:
        if context:
            try:
                context.close()
            except Exception:
                pass


def run_worker():
    # Generate run ID
    worker_run_id = f"job-url-content-{int(time.time())}"
    print(f"Starting job URL content worker. run_id={worker_run_id}")

    with sync_playwright() as p:
        browser = launch_browser(p)
        processed_since_launch = 0

        while True:
            claim = None
            try:
                claim = fetch_next_job_content_job(worker_run_id=worker_run_id)
                if not claim:
                    print(f"No job URL tasks ready. Sleeping {POLL_SLEEP_SECONDS}s...")
                    time.sleep(POLL_SLEEP_SECONDS)
                    continue

                restart_browser = process_job_content(claim, browser, worker_run_id)
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
                time.sleep(POLL_SLEEP_SECONDS)


if __name__ == "__main__":
    run_worker()
