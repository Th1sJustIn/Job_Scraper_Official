from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from markdownify import markdownify as md
import time
import re
import json

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

def normalize(text):
    # Collapse multiple newlines to max 2
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Collapse multiple spaces/tabs to single space
    text = re.sub(r'[ \t]+', ' ', text)
    return text.strip()

def clean_html(html):
    soup = BeautifulSoup(html, "lxml")
    for tag in REMOVE_TAGS:
        for element in soup.find_all(tag):
            element.decompose()
    return str(soup)

def scrape_instacart_careers():
    url = "https://instacart.careers/current-openings/"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
             user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        page = context.new_page()
        
        try:
            print(f"Navigating to {url}...")
            page.goto(url)
            
            # Wait for content to load.
            page.wait_for_load_state("networkidle")
            
            # Additional wait to ensure dynamic content rendering
            time.sleep(5) 
            
            html_content = page.content()
            print("Page content retrieved. Cleaning HTML...")
            
            cleaned_html = clean_html(html_content)
            
            # Save cleaned HTML
            cleaned_html_file = "instacart_cleaned.html"
            with open(cleaned_html_file, "w", encoding="utf-8") as f:
                f.write(cleaned_html)
            print(f"Successfully saved cleaned HTML to {cleaned_html_file}")
            
            print("Converting to markdown...")
            markdown_content = md(cleaned_html, strip=['img'])
            
            if markdown_content:
                print("Normalizing markdown content...")
                markdown_content = normalize(markdown_content)
                
                # Chunking content
                print("Chunking content...")
                chunks = chunk_text(markdown_content)
                
                output_data = [{
                    "chunks": chunks,
                    "total_num_of_chunks": len(chunks)
                }]
                
                output_file = "instacart_openings.json"
                with open(output_file, "w", encoding="utf-8") as f:
                    json.dump(output_data, f, indent=4)
                print(f"Successfully saved to {output_file}")
            else:
                print("Failed to convert content.")
                
        except Exception as e:
            print(f"An error occurred: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    scrape_instacart_careers()
