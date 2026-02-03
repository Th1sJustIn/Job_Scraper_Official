
import csv
import sys
from database.client import get_supabase_client

def import_companies(csv_file_path):
    supabase = get_supabase_client()
    
    print(f"Reading from {csv_file_path}...")
    
    try:
        with open(csv_file_path, mode='r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            
            # Normalize headers just in case of whitespace
            reader.fieldnames = [name.strip() for name in reader.fieldnames]
            
            if 'company' not in reader.fieldnames or 'careers_url' not in reader.fieldnames:
                print("Error: CSV must contain 'company' and 'careers_url' headers.")
                return

            stats = {"companies_added": 0, "urls_added": 0, "skipped": 0}

            for row in reader:
                company_name = row['company'].strip()
                url = row['careers_url'].strip()
                
                if not company_name or not url:
                    continue

                # 1. Check if URL already exists
                existing_url = (
                    supabase
                    .table("career_pages")
                    .select("id")
                    .eq("url", url)
                    .execute()
                )
                if existing_url.data:
                    print(f"Skipping {url}: Already exists.")
                    stats["skipped"] += 1
                    continue
                
                # 2. Check/Insert Company
                company_id = None
                existing_company = (
                    supabase
                    .table("companies")
                    .select("id")
                    .eq("name", company_name)
                    .execute()
                )                
                if existing_company.data:
                    company_id = existing_company.data[0]["id"]
                    print(f"Using existing company: {company_name} (ID: {company_id})")
                else:
                    new_company = supabase.table("companies").insert({"name": company_name}).execute()
                    if new_company.data:
                        company_id = new_company.data[0]["id"]
                        print(f"Added new company: {company_name} (ID: {company_id})")
                        stats["companies_added"] += 1
                    else:
                        print(f"Error adding company: {company_name}")
                        continue
                
                # 3. Insert URL
                if company_id:
                    new_page = supabase.table("career_pages").insert({
                        "company_id": company_id,
                        "url": url
                    }).execute()
                    if new_page.data:
                        print(f"Added URL for {company_name}: {url}")
                        stats["urls_added"] += 1
                    else:
                        print(f"Error adding URL: {url}")

            print("\nImport Complete!")
            print(f"Companies Added: {stats['companies_added']}")
            print(f"URLs Added: {stats['urls_added']}")
            print(f"Skipped (Duplicate URLs): {stats['skipped']}")

    except FileNotFoundError:
        print(f"Error: File '{csv_file_path}' not found.")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        csv_path = sys.argv[1]
    else:
        # Default fallback usually good for dev
        csv_path = "test_companies.csv"
        
    import_companies(csv_path)
