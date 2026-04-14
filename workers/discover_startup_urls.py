import json
import csv
import time
import argparse
import requests
import urllib.parse
import os
from bs4 import BeautifulSoup
import re

IGNORE_DOMAINS = [
    "topstartups.io",
    "linkedin.com",
    "crunchbase.com",
    "ycombinator.com",
    "glassdoor.com",
    "pitchbook.com",
    "wellfound.com",
    "builtin.com",
    "en.wikipedia.org",
    "twitter.com",
    "facebook.com",
    "instagram.com",
    "youtube.com",
    "apple.com",
    "medium.com",
    "forbes.com",
    "techcrunch.com"
]

def is_valid_url(url):
    url_lower = url.lower()
    for domain in IGNORE_DOMAINS:
        if domain in url_lower:
            return False
    return True

def search_clearbit(company_name):
    """Search using Clearbit Autocomplete API."""
    try:
        url = f"https://autocomplete.clearbit.com/v1/companies/suggest?query={urllib.parse.quote_plus(company_name)}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        r = requests.get(url, headers=headers, timeout=5)
        if r.status_code == 200:
            data = r.json()
            if data and len(data) > 0:
                # Try to find an exact name match first
                for item in data:
                    if item.get("name", "").lower() == company_name.lower():
                        return f"https://{item['domain']}"
                # Fallback to the first result
                domain = data[0].get("domain")
                if domain:
                    return f"https://{domain}"
    except Exception:
        pass
    return None

def search_duckduckgo(company_name, industry):
    """DuckDuckGo HTML search as a fallback."""
    try:
        query = f'"{company_name}" {industry} startup official site'
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote_plus(query)}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        r = requests.get(url, headers=headers, timeout=10)
        
        if r.status_code != 200:
            return ""
            
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", class_="result__url"):
            href = a.get("href")
            if href:
                if "duckduckgo.com/l/?uddg=" in href:
                    href = urllib.parse.unquote(href.split("uddg=")[1].split("&")[0])
                if is_valid_url(href):
                    return href
    except Exception:
        pass
    return ""

def find_startup_url(company_name, industry):
    # 1. Try Clearbit API (Fast, reliable, but can sometimes guess the wrong company for generic names)
    url = search_clearbit(company_name)
    if url:
        return url
        
    # 2. Fallback to DDG Search (Rate limited quickly)
    time.sleep(2.5) 
    return search_duckduckgo(company_name, industry)

def main():
    parser = argparse.ArgumentParser(description="Discover startup URLs.")
    parser.add_argument("--test", action="store_true", help="Run in test mode (only process the first 5 startups).")
    args = parser.parse_args()

    input_file = "data/startup_names.json"
    output_file = "data/Startup_Urls.csv"
    
    try:
        with open(input_file, "r") as f:
            startups = json.load(f)
    except FileNotFoundError:
        print(f"Error: Could not find {input_file}")
        return

    if args.test:
        print("Running in TEST mode. Only processing first 5 startups.")
        startups = startups[:5]
        output_file = "data/Startup_Urls_Test.csv"
    
    print(f"Processing {len(startups)} startups...")

    with open(output_file, "w", newline="", encoding="utf-8") as csvfile:
        fieldnames = ["Company", "Industry", "Website"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        
        for idx, startup in enumerate(startups, 1):
            company_name = startup.get("company name", "")
            industry = startup.get("industry", "")
            
            if not company_name:
                continue

            print(f"[{idx}/{len(startups)}] Searching for: {company_name} ({industry})", end="", flush=True)
            
            url = find_startup_url(company_name, industry)
            
            if url:
                print(f" -> Found: {url}")
            else:
                print(f" -> No valid URL found.")
            
            writer.writerow({
                "Company": company_name,
                "Industry": industry,
                "Website": url
            })
            csvfile.flush()
            
    print(f"\nDone! Results saved to {output_file}")

if __name__ == "__main__":
    # Ensure database module is findable if needed (though not currently used in this script)
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if parent_dir not in os.sys.path:
        os.sys.path.insert(0, parent_dir)
        
    main()
