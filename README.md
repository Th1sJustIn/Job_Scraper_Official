# Job Scraper & Big Data Analytics Pipeline

## Project Description
This project is a multi-stage data pipeline that ingests company career-page URLs, extracts content using Playwright, normalizes job listings with AI (LLM), and performs distributed analytical processing using Apache Spark.

Current milestone focus: **CS4265 Milestone 3 (M3) - Big Data Integration**.  
The M3 goal is to bridge the gap between transactional scraping and large-scale analytical processing by introducing a distributed data layer.

## M3 Status (Current)
- **Transactional Pipeline**: Operational (Acquisition, AI Extraction, Supabase Storage).
- **Big Data Bridge**: Implemented (Automated ETL from Supabase to Parquet Data Lake).
- **Distributed Analytics**: Implemented (PySpark-based Tech-Stack and Salary aggregations).
- **Data Lake Architecture**: Medallion-style (Bronze/Gold) storage implemented.

## Pipeline Components

### 1. Scraping & Extraction (OLTP)
- **`import_companies.py`**: Loads companies into Supabase.
- **`extract_site_content.py`**: Fetches HTML and converts to cleaned markdown chunks.
- **`job_extraction.py`**: Uses LLMs to identify and normalize job listings.
- **`extract_job_url_content.py`**: Verifies and fetches individual job post URLs.

### 2. Big Data & Analytics (OLAP)
- **`database/big_data/exporter.py`**: Syncs Supabase data into a local **Parquet Data Lake** (Bronze Layer) using paginated requests.
- **`analytics/spark_analytics.py`**: A **PySpark** distributed processing job that performs:
  - Tech Stack Popularity ranking (Explode/Aggregate).
  - Salary Benchmarking by Department (Shuffle Join).
  - System Reliability Analysis (Log Diagnostics).

## Repository Structure
```text
project/
  analytics/
    spark_analytics.py      <-- Distributed Processing
  database/
    big_data/
      exporter.py           <-- ETL Bridge
    AI_connection/
    client.py
    database.py
  datalake/                 <-- Local Parquet Data Lake
    bronze/
    gold/
  docs/
  supabase/
    migrations/
  requirements.txt
```

## Prerequisites
- **Python 3.14+**
- **Java 11 or 17** (Required for Apache Spark)
- **Apache Spark / PySpark 3.5.0**
- Playwright & Supabase credentials

## Setup
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

## Run Commands

### 1. Data Ingestion & Scraping
```bash
# Import sources
python import_companies.py test_companies.csv

# Run workers (Orchestrated via Supabase status states)
python extract_site_content.py
python job_extraction.py
```

### 2. Big Data Analysis
This single command automatically syncs the Data Lake from Supabase and runs the distributed Spark analytics:
```bash
python3 -m analytics.spark_analytics
```

## Outputs / Storage
- **Transactional (Supabase)**: `companies`, `career_pages`, `scrapes`, `jobs`, `scrape_log_events`.
- **Analytical (Parquet)**: Columnar storage in `datalake/` for high-volume distributed access.

## Security
- Secrets are managed via `.env` (excluded from git).
- All Big Data processing is local-mode to ensure data privacy.
