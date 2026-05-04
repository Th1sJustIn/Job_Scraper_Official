# Data Dictionary

This document defines the core schema of the Job Scraper & Big Data Analytics Pipeline. The data is originally stored in PostgreSQL (Supabase) and exported identically to the Bronze Layer Data Lake in Parquet format.

## `companies`
Stores the target startup companies and their primary metadata.
| Column Name | Data Type | Description |
|---|---|---|
| `id` | UUID (PK) | Unique identifier for the company. |
| `name` | String | The legal or trading name of the startup. |
| `domain` | String | The primary website domain (e.g., `stripe.com`). |
| `created_at` | Timestamp | When the record was created. |

## `career_pages`
Stores the discovered career URLs or ATS endpoints for each company.
| Column Name | Data Type | Description |
|---|---|---|
| `id` | UUID (PK) | Unique identifier for the career page record. |
| `company_id` | UUID (FK) | References `companies.id`. |
| `url` | String | The URL of the careers page or ATS board. |
| `discovery_method` | String | How the URL was found (e.g., `manual`, `clearbit`, `duckduckgo`). |
| `last_checked_at` | Timestamp | The last time the pipeline attempted to scrape this URL. |

## `scrapes`
Logs individual scrape attempts of career pages, facilitating the status-driven orchestration.
| Column Name | Data Type | Description |
|---|---|---|
| `id` | UUID (PK) | Unique identifier for the scrape attempt. |
| `career_page_id` | UUID (FK) | References `career_pages.id`. |
| `status` | String | Pipeline state (e.g., `pending`, `scraping`, `parsing`, `completed`, `failed`). |
| `raw_html_path` | String | Reference to the raw HTML stored in cloud storage (if applicable). |
| `cleaned_markdown` | Text | The Playwright-extracted and cleaned markdown text. |
| `created_at` | Timestamp | When the scrape job was initiated. |

## `jobs`
The normalized output of the LLM extraction containing high-level job metadata.
| Column Name | Data Type | Description |
|---|---|---|
| `id` | UUID (PK) | Unique identifier for the job. |
| `company_id` | UUID (FK) | References `companies.id`. |
| `scrape_id` | UUID (FK) | References `scrapes.id` (lineage tracking). |
| `title` | String | The job title (e.g., "Senior Data Engineer"). |
| `department` | String | The department or team (e.g., "Engineering", "Sales"). |
| `location` | String | Geographic location or "Remote". |
| `job_url` | String | Direct URL to apply to the job. |
| `status` | String | Job state (e.g., `open`, `closed`). |
| `created_at` | Timestamp | When the job was inserted into the database. |

## `job_descriptions`
Detailed metadata extracted from the specific job posting URL.
| Column Name | Data Type | Description |
|---|---|---|
| `id` | UUID (PK) | Unique identifier for the description record. |
| `job_id` | UUID (FK) | References `jobs.id`. |
| `salary_min` | Numeric | Minimum extracted salary bound. |
| `salary_max` | Numeric | Maximum extracted salary bound. |
| `years_experience_min` | Integer | Minimum required years of experience. |
| `tech_stack` | Array[String] | Array of technical skills required (e.g., `["Python", "Spark"]`). |
| `full_text` | Text | The raw text of the job description. |

## `scrape_log_events`
Audit table containing system events, errors, and warnings for reliability analysis.
| Column Name | Data Type | Description |
|---|---|---|
| `id` | UUID (PK) | Unique identifier for the log event. |
| `worker` | String | Which script/worker generated the event (e.g., `extract_site_content`). |
| `event_type` | String | Category of the event (e.g., `timeout`, `parse_error`, `success`). |
| `severity` | String | Log level (`info`, `warning`, `error`). |
| `message` | Text | Detailed log message or stack trace. |
| `created_at` | Timestamp | When the event occurred. |
