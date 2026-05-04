import os
import sys
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from database.big_data.exporter import export_to_parquet

# Spark 3/4 requires Java 8, 11, or 17. Java 24 is too new and causes Subject.getSubject errors.
os.environ["JAVA_HOME"] = "/Library/Java/JavaVirtualMachines/amazon-corretto-11.jdk/Contents/Home"

def run_analytics():
    # Automatically sync data from Supabase first
    export_to_parquet()
    
    print("\n🚀 Starting Distributed Analytics (PySpark)...")
    
    # Initialize Spark Session (Local Mode)
    # Using all available cores [*]
    spark = SparkSession.builder \
        .appName("JobScraper_BigData_Analysis") \
        .master("local[*]") \
        .getOrCreate()
    
    print("✅ Spark Session Active.")
    
    # --- LOAD DATA (Bronze Layer) ---
    print("📂 Loading Bronze Layer Parquet files...")
    df_jobs = spark.read.parquet("datalake/bronze/jobs.parquet")
    df_desc = spark.read.parquet("datalake/bronze/job_descriptions.parquet")
    df_logs = spark.read.parquet("datalake/bronze/scrape_log_events.parquet")
    
    print(f"📊 Total Records Loaded for Analysis:")
    print(f"   • Jobs: {df_jobs.count()}")
    print(f"   • Descriptions: {df_desc.count()}")
    print(f"   • Logs: {df_logs.count()}")
    
    # --- ANALYTICS 1: Tech Stack Popularity ---
    print("📊 Computing Tech Stack Popularity (Distributed Aggregation)...")
    # explode tech_stack array into individual rows
    tech_stats = df_desc.select(F.explode("tech_stack").alias("tech_item")) \
        .groupBy("tech_item") \
        .count() \
        .orderBy("count", ascending=False)
    
    print("Top Tech Skills Extracted:")
    tech_stats.show(10)
    
    # --- ANALYTICS 2: Salary & Experience benchmarking ---
    print("📊 Computing Salary & Experience Benchmarks by Department...")
    # Join jobs and descriptions to get department context
    joined_df = df_desc.join(df_jobs.select("id", "department"), df_desc.job_id == df_jobs.id)
    
    salary_benchmarks = joined_df.groupBy("department").agg(
        F.avg("salary_min").alias("avg_min_salary"),
        F.avg("salary_max").alias("avg_max_salary"),
        F.avg("years_experience_min").alias("avg_exp_required"),
        F.count("job_id").alias("sample_size")
    ).orderBy("avg_max_salary", ascending=False)
    
    salary_benchmarks.show()
    
    # --- ANALYTICS 3: System Reliability (Log Analysis) ---
    print("📊 Computing Scraper Reliability Matrix (Log Analytics)...")
    # Calculate error rates per worker
    reliability = df_logs.groupBy("worker", "event_type").count() \
        .withColumn("is_error", F.when(F.col("event_type").contains("error") | F.col("event_type").contains("fail"), 1).otherwise(0))
    
    # More advanced: percent of failures vs successes
    health_matrix = df_logs.groupBy("worker").agg(
        F.count("*").alias("total_events"),
        F.sum(F.when(F.col("severity") == "error", 1).otherwise(0)).alias("error_count")
    ).withColumn("error_rate", F.col("error_count") / F.col("total_events")) \
     .orderBy("error_rate", ascending=False)
    
    health_matrix.show()
    
    # --- ANALYTICS 4: Top Job Titles ---
    print("📊 Computing Most Common Job Titles...")
    top_titles = df_jobs.groupBy("title") \
        .count() \
        .orderBy("count", ascending=False)
    
    top_titles.show(10)

    # --- SAVE RESULTS (Gold Layer) ---
    print("\n💾 Saving results to Gold Layer...")
    output_path = "datalake/gold"
    tech_stats.write.mode("overwrite").parquet(f"{output_path}/tech_popularity")
    salary_benchmarks.write.mode("overwrite").parquet(f"{output_path}/salary_benchmarks")
    health_matrix.write.mode("overwrite").parquet(f"{output_path}/system_health")
    top_titles.write.mode("overwrite").parquet(f"{output_path}/top_titles")
    
    print(f"✅ Success! Gold Layer saved to {output_path}")

    # --- FINAL SUMMARY PRINT ---
    print("\n" + "="*50)
    print("       🚀 BIG DATA ANALYTICS REPORT 🚀")
    print("="*50)
    
    print("\n1. TOP 5 JOB TITLES:")
    titles = top_titles.limit(5).collect()
    for row in titles:
        print(f"   • {row['title']}: {row['count']} postings")

    print("\n2. TOP 5 TECH SKILLS IN DEMAND:")
    top_tech = tech_stats.limit(5).collect()
    for row in top_tech:
        print(f"   • {row['tech_item']}: {row['count']} mentions")
        
    print("\n2. SALARY BENCHMARKS BY DEPT:")
    sal_bench = salary_benchmarks.limit(3).collect()
    for row in sal_bench:
        dept = row['department'] if row['department'] else "General"
        avg_sal = f"${row['avg_max_salary']:,.0f}" if row['avg_max_salary'] else "N/A"
        print(f"   • {dept}: Avg Max Salary {avg_sal} ({row['sample_size']} jobs)")

    print("\n3. SYSTEM RELIABILITY (DISTRIBUTED LOGS):")
    h_matrix = health_matrix.limit(3).collect()
    for row in h_matrix:
        rate = f"{row['error_rate']*100:.1f}%"
        print(f"   • Worker: {row['worker']} | Error Rate: {rate}")

    print("\n" + "="*50)
    print("✅ ANALYSIS COMPLETE")
    print("="*50)

    spark.stop()

if __name__ == "__main__":
    run_analytics()
