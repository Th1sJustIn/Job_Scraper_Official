import os
import pandas as pd
from database.client import get_supabase_client
from pathlib import Path

def export_to_parquet():
    """
    ETL Bridge: Fetches data from Supabase and exports to Parquet format.
    This simulates a 'Bronze Layer' in a Big Data Medallion Architecture.
    """
    print("Starting Big Data Export (ETL Phase)...")
    
    supabase = get_supabase_client()
    
    # Define target tables to export
    tables = [
        "jobs",
        "job_descriptions",
        "scrape_log_events"
    ]
    
    # Ensure datalake directory exists
    base_path = Path("datalake/bronze")
    base_path.mkdir(parents=True, exist_ok=True)
    
    for table_name in tables:
        print(f"📦 Exporting table: {table_name}...")
        
        try:
            # Implement Pagination to bypass Supabase's 1,000 row limit
            all_data = []
            page_size = 1000
            offset = 0
            
            while True:
                response = supabase.table(table_name).select("*") \
                    .range(offset, offset + page_size - 1) \
                    .execute()
                
                data = response.data
                if not data:
                    break
                    
                all_data.extend(data)
                
                if len(data) < page_size:
                    break
                    
                offset += page_size
                # Global safety cap from your previous edit
                if offset >= 100000:
                    break
            
            if not all_data:
                print(f"⚠️ No data found in table {table_name}. Skipping.")
                continue
                
            # Convert to Pandas DataFrame
            df = pd.DataFrame(all_data)
            
            # Define file path
            file_path = base_path / f"{table_name}.parquet"
            
            # Save to Parquet using pyarrow engine
            df.to_parquet(file_path, engine="pyarrow", index=False)
            
            print(f"✅ Successfully exported {len(df)} rows to {file_path}")
            
        except Exception as e:
            print(f"❌ Failed to export {table_name}: {e}")

if __name__ == "__main__":
    # Ensure we are running from the project root
    export_to_parquet()
