from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from markdownify import markdownify as md
import time
import re
import json
import hashlib
from database.database import get_career_page_url, get_career_pages, create_scrape_job, update_scrape_job, fail_scrape_job, get_latest_scrape_hash, is_recently_scraped

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

def extract_content(career_page_id):
    
    # Check for recent successful scrape
    if is_recently_scraped(career_page_id):
        print(f"Skipping career_page_id {career_page_id}: Scraped successfully within last 20 hours.")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
             user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        page = context.new_page()

        url = get_career_page_url(career_page_id)
        scrape_id = None
        try:
            print(f"Navigating to {url}...")
            page.goto(url)
            
            # Wait for content to load.
            page.wait_for_load_state("networkidle")
            
            # Additional wait to ensure dynamic content rendering
            time.sleep(5) 
            
            html_content = page.content()
            html_hash = hashlib.md5(html_content.encode('utf-8')).hexdigest()
            print(f"Content Hash: {html_hash}")

            # Check for duplicate
            last_hash = get_latest_scrape_hash(career_page_id)
            if last_hash and last_hash == html_hash:
                print(f"Content unchanged (Hash match). Skipping processing.")
                return

            # Content is new, create job
            scrape_id = create_scrape_job(career_page_id)

            print("Page content retrieved. Cleaning HTML...")
            
            cleaned_html = clean_html(html_content)
            
            # Save cleaned HTML (optional keeping for debug)
            # cleaned_html_file = "rippling_cleaned.html"
            # with open(cleaned_html_file, "w", encoding="utf-8") as f:
            #     f.write(cleaned_html)
            # print(f"Successfully saved cleaned HTML to {cleaned_html_file}")
            
            print("Converting to markdown...")
            markdown_content = md(cleaned_html, strip=['img'])
            
            if markdown_content:
                print("Normalizing markdown content...")
                markdown_content = normalize(markdown_content)

                # Save markdown content (optional keeping for debug)
                # md_output_file = "rippling_openings.md"
                # with open(md_output_file, "w", encoding="utf-8") as f:
                #     f.write(markdown_content)
                # print(f"Successfully saved to {md_output_file}")
                
                # Chunking content
                print("Chunking content...")
                chunks = chunk_text(markdown_content)
                
                # Send to DB
                print("Updating scrape job in database...")
                update_scrape_job(
                    scrape_id=scrape_id,
                    raw_html=cleaned_html, # Using cleaned HTML as 'raw' here for storage efficiency, or user might want true raw? "raw_html" usually implies pre-processing. Sticking to cleaned for utility. Actually schema says "raw_html". I'll use clean_html result or actual raw? The prompt said "send up the html". Usually raw is raw. But `clean_html` strips scripts etc which is good. I will store the *cleaned* html in the raw_html column for now as it's more useful, or I could store the actual raw page.content(). The user code saved cleaned_html to file. I'll store cleaned_html to keep it cleaner.
                    markdown=markdown_content,
                    chunks=chunks,
                    chunk_count=len(chunks),
                    html_hash=html_hash
                )
                print("Scrape job completed successfully.")
            else:
                print("Failed to convert content.")
                fail_scrape_job(scrape_id, "Failed to convert content to markdown")
                
        except Exception as e:
            print(f"An error occurred: {e}")
            if scrape_id:
                fail_scrape_job(scrape_id, str(e))
            else:
                scrape_id = create_scrape_job(career_page_id)
                fail_scrape_job(scrape_id, str(e))
        finally:
            browser.close()

if __name__ == "__main__":
    career_pages = get_career_pages()
    
    for career_page in career_pages:
        extract_content(career_page["id"])