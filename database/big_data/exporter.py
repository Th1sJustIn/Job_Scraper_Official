import os
from pathlib import Path
from pyspark.sql import SparkSession
from dotenv import load_dotenv

def export_to_parquet():
    """
    ETL Bridge: Fetches data from Supabase and exports to Parquet format.
    This uses PySpark JDBC for a distributed 'Bronze Layer' read.
    """
    print("Starting Big Data Export (ETL Phase) via PySpark JDBC...")
    
    load_dotenv()
    project_url = os.environ.get("SUPABASE_PROJECT_URL")
    password = os.environ.get("SUPABASE_DB_PASSWORD")
    
    if not project_url or not password:
        raise ValueError("Missing SUPABASE_PROJECT_URL or SUPABASE_DB_PASSWORD in .env")
        
    # Extract project ref from URL (e.g. https://pipckiizyixhftmklaww.supabase.co)
    project_ref = project_url.replace("https://", "").split(".")[0]
    
    # Allow overriding the JDBC URL (useful for Supabase connection pooler or IPv4 issues)
    jdbc_url = os.environ.get("SUPABASE_JDBC_URL")
    if not jdbc_url:
        jdbc_url = f"jdbc:postgresql://db.{project_ref}.supabase.co:5432/postgres"
    
    # Initialize Spark Session with PostgreSQL driver
    spark = SparkSession.builder \
        .appName("JobScraper_BigData_Ingestion") \
        .config("spark.jars.packages", "org.postgresql:postgresql:42.6.0") \
        .master("local[*]") \
        .getOrCreate()
    
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
        print(f"📦 Exporting table: {table_name} via PySpark JDBC...")
        
        try:
            # Read via JDBC into a Spark DataFrame
            df = spark.read.format("jdbc") \
                .option("url", jdbc_url) \
                .option("dbtable", table_name) \
                .option("user", "postgres") \
                .option("password", password) \
                .option("driver", "org.postgresql.Driver") \
                .load()
            
            # Save to Parquet in the Bronze Layer
            file_path = str(base_path / f"{table_name}.parquet")
            df.write.mode("overwrite").parquet(file_path)
            
            print(f"✅ Successfully exported {table_name} to {file_path}")
            
        except Exception as e:
            print(f"❌ Failed to export {table_name}: {e}")
            
    spark.stop()

if __name__ == "__main__":
    # Ensure we are running from the project root
    export_to_parquet()
