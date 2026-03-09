import csv
import re
import time
import requests
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
import urllib3

# Suppress insecure request warnings for pages with bad SSL certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Common headers to avoid 403
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
}

ATS_PATTERNS = [
    r'https?://(?:boards|job-boards|api)\.greenhouse\.io/[a-zA-Z0-9_-]+',
    r'https?://jobs\.lever\.co/[a-zA-Z0-9_-]+',
    r'https?://jobs\.ashbyhq\.com/[a-zA-Z0-9_-]+',
    r'https?://apply\.workable\.com/[a-zA-Z0-9_-]+',
    r'https?://[a-zA-Z0-9_-]+\.breezy\.hr',
    r'https?://jobs\.gusto\.com/boards/[a-zA-Z0-9_-]+',
    r'https?://careers\.hireology\.com/[a-zA-Z0-9_-]+',
    r'https?://[a-zA-Z0-9_-]+\.workable\.com',
]

ATS_REGEX = re.compile('|'.join(ATS_PATTERNS), re.IGNORECASE)

def generate_slugs(company, website):
    slugs = set()
    
    # 1. From company name
    # remove punctuation and spaces
    c_clean = re.sub(r'[^a-zA-Z0-9]', '', company.lower())
    if c_clean: slugs.add(c_clean)
    
    # with hyphens for spaces
    c_hyphen = re.sub(r'[^a-zA-Z0-9 ]', '', company.lower()).strip().replace(' ', '-')
    if c_hyphen: slugs.add(c_hyphen)
    
    # split by space and take first word if multiple
    parts = company.lower().split()
    if len(parts) > 1:
        clean_first = re.sub(r'[^a-zA-Z0-9]', '', parts[0])
        if clean_first: slugs.add(clean_first)
    
    # 2. From domain
    if website:
        try:
            parsed = urlparse(website if website.startswith('http') else 'http://' + website)
            domain = parsed.netloc if parsed.netloc else parsed.path
            domain = domain.replace('www.', '')
            base = domain.split('.')[0]
            if base:
                slugs.add(base)
                slugs.add(base.replace('-', ''))
        except Exception:
            pass
            
    # Remove empty strings
    return [s for s in slugs if s]

def check_ats_url(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=5, allow_redirects=True, verify=False)
        # Many ATS boards return 404 for missing companies, but some like Ashby return 200 with generic content
        if resp.status_code == 200:
            if 'lever.co' in url and resp.url == 'https://jobs.lever.co/':
                return False
            if 'ashbyhq.com' in url and '<title>Jobs</title>' in resp.text:
                return False
            if 'greenhouse.io' in url and 'form id="search_form"' not in resp.text and 'class="job-boards"' not in resp.text and 'jobs' not in resp.text.lower():
                # rough heuristic for false positive greenhouse
                pass
            return True
    except requests.RequestException:
        pass
    return False

def guess_ats(slugs):
    # try the easiest ones that use simple slug endpoints
    # Ordered by likelihood for tech startups
    platforms = [
        "https://boards.greenhouse.io/{}",
        "https://jobs.lever.co/{}",
        "https://jobs.ashbyhq.com/{}"
    ]
    for slug in slugs:
        for p in platforms:
            url = p.format(slug)
            if check_ats_url(url):
                return url
    return None

def find_ats_on_page(url):
    if not url.startswith('http'):
        url = 'https://' + url
    
    ats_match = None
    custom_url = None
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10, allow_redirects=True, verify=False)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            for tag in soup.find_all(['a', 'iframe']):
                link = tag.get('href') or tag.get('src')
                if link:
                    match = ATS_REGEX.search(link)
                    if match:
                        ats_match = match.group(0)
                        break
            
            if not ats_match:
                parsed_original = urlparse(url)
                parsed_final = urlparse(resp.url)
                text = resp.text.lower()
                if 'career' in parsed_final.path.lower() or 'job' in parsed_final.path.lower() or parsed_original.path.strip('/') in parsed_final.path or 'open positions' in text or 'job openings' in text:
                    custom_url = resp.url
                    
    except Exception:
        pass
    return ats_match, custom_url

def process_company(row):
    company = row.get('Company', '')
    industry = row.get('Industry', '')
    website = row.get('Website', '')
    
    result = {'Company': company, 'Industry': industry, 'Website': website, 'ATS_Url': '', 'Method': ''}
    
    slugs = generate_slugs(company, website)
    
    print(f"[*] Processing: {company} ({website}) - Slugs: {slugs}")
    
    # 1. Guess
    ats_url = guess_ats(slugs)
    if ats_url:
        result['ATS_Url'] = ats_url
        result['Method'] = 'URL_Guess'
        return result
        
    # 2. Site Parse
    if website:
        # Check homepage
        ats_url, _ = find_ats_on_page(website)
        if ats_url:
             result['ATS_Url'] = ats_url
             result['Method'] = 'Site_Homepage'
             return result
             
        # Check common career paths
        paths_to_check = ['/careers', '/jobs', '/work-with-us', '/join-us', '/opportunities', '/careers-at', '/open-positions', '/current-openings', '/we-are-hiring', '/employment']
        best_custom_url = None
        best_custom_method = None
        
        for path in paths_to_check:
             check_url = website.rstrip('/') + path
             ats_url, custom_url = find_ats_on_page(check_url)
             if ats_url:
                  result['ATS_Url'] = ats_url
                  result['Method'] = f'Site_{path.strip("/")}'
                  return result
             elif custom_url and not best_custom_url:
                  best_custom_url = custom_url
                  best_custom_method = f'Custom_{path.strip("/")}_Page'

        if best_custom_url:
             result['ATS_Url'] = best_custom_url
             result['Method'] = best_custom_method
             return result
             
    return result

def main(input_file, output_file, max_workers):
    rows = []
    with open(input_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
            
    print(f"Targeting {len(rows)} companies from {input_file}...")
    
    results = []
    found_count = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_row = {executor.submit(process_company, row): row for row in rows}
        for future in as_completed(future_to_row):
            res = future.result()
            results.append(res)
            if res['ATS_Url']:
                print(f"[SUCCESS] {res['Company']}: {res['ATS_Url']} via {res['Method']}")
                found_count += 1
            else:
                print(f"[MISS] {res['Company']}")
                
    with open(output_file, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['Company', 'Industry', 'Website', 'ATS_Url', 'Method'])
        writer.writeheader()
        for res in results:
            writer.writerow(res)
            
    print(f"\nDone! Found ATS links for {found_count}/{len(rows)} companies.")
    print(f"Results saved to {output_file}.")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('input_csv', help='Path to input CSV file')
    parser.add_argument('output_csv', help='Path to output CSV file')
    parser.add_argument('--workers', type=int, default=10, help='Max concurrent workers')
    args = parser.parse_args()
    
    main(args.input_csv, args.output_csv, args.workers)
