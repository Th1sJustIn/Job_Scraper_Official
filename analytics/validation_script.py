import sys
from pyspark.sql import SparkSession
from pyspark.sql import functions as F

def run_validation():
    print("🚀 Starting Data Validation Checks (M4)...")
    
    spark = SparkSession.builder \
        .appName("JobScraper_Validation") \
        .master("local[*]") \
        .getOrCreate()
        
    try:
        df_jobs = spark.read.parquet("datalake/bronze/jobs.parquet")
        df_desc = spark.read.parquet("datalake/bronze/job_descriptions.parquet")
        df_logs = spark.read.parquet("datalake/bronze/scrape_log_events.parquet")
    except Exception as e:
        print(f"❌ Failed to load Bronze layer Data: {e}")
        print("Please run database/big_data/exporter.py to sync the Data Lake first.")
        spark.stop()
        sys.exit(1)
        
    # 1. Completeness & Row Counts
    job_count = df_jobs.count()
    desc_count = df_desc.count()
    log_count = df_logs.count()
    
    print("\n--- 1. COMPLETENESS METRICS ---")
    print(f"Total Jobs Extracted: {job_count}")
    print(f"Total Job Descriptions Parsed: {desc_count}")
    print(f"Total Event Logs Recorded: {log_count}")
    
    if job_count > 0:
        completeness_ratio = (desc_count / job_count) * 100
        print(f"Description Extraction Completeness: {completeness_ratio:.1f}%")
        
    # 2. Null Rates (Data Quality)
    print("\n--- 2. DATA QUALITY: NULL RATES ---")
    def calculate_nulls(df, table_name):
        print(f"\n{table_name} Table:")
        total = df.count()
        if total == 0:
            print("Table is empty.")
            return
        for col_name in df.columns:
            # For string columns we also check for empty strings
            null_count = df.filter(F.col(col_name).isNull() | (F.col(col_name) == "")).count()
            null_pct = (null_count / total) * 100
            print(f"  - {col_name}: {null_pct:.1f}% null ({null_count}/{total})")
            
    calculate_nulls(df_jobs, "Jobs")
    calculate_nulls(df_desc, "Job Descriptions")
    
    # 3. Reasonableness & Constraints
    print("\n--- 3. REASONABLENESS CHECKS ---")
    duplicate_jobs = df_jobs.groupBy("title", "company_id").count().filter(F.col("count") > 1).count()
    print(f"Duplicate Job Title/Company Pairs: {duplicate_jobs}")
    
    # 4. Sample Tracing
    print("\n--- 4. SAMPLE TRACING (End-to-End) ---")
    print("Tracing a single job record through the pipeline:")
    sample_job = df_jobs.limit(1).collect()
    if sample_job:
        job_id = sample_job[0]["id"]
        title = sample_job[0]["title"]
        print(f"Selected Job ID: {job_id} | Title: {title}")
        
        desc_match = df_desc.filter(F.col("job_id") == job_id).count()
        print(f"Description found in bronze layer? {'Yes' if desc_match > 0 else 'No'}")
    else:
        print("No jobs found to trace.")
        
    print("\n✅ Validation Complete. See docs/validation.md for the full formal report.")
    spark.stop()

if __name__ == "__main__":
    run_validation()
