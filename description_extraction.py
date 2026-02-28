import time
import json
from datetime import datetime, timezone
from database.database import (
    fetch_next_description_extraction_job,
    update_job_page_fetch_status,
    insert_job_description,
    log_scrape_event
)
from database.AI_connection.AI import (
    extract_job_description_from_markdown,
    ensure_llm_server_available,
    LLMConnectionError,
)

def process_description_extraction(fetch_record, worker_run_id):
    fetch_id = fetch_record.get("id")
    job_id = fetch_record.get("job_id")
    markdown = fetch_record.get("markdown")

    if not markdown:
        raise ValueError(f"Missing markdown for fetch_id {fetch_id}")

    print(f"\nProcessing Description Extraction for Fetch ID: {fetch_id} (Job ID: {job_id})")
    print(f"Markdown length: {len(markdown)} characters")

    ensure_llm_server_available()
    
    ai_start = time.time()
    extracted_data = extract_job_description_from_markdown(markdown)
    ai_duration = int((time.time() - ai_start) * 1000)
    
    # Log AI Extraction
    log_scrape_event(
        scrape_id=fetch_id, # Using fetch_id as scrape_id placeholder
        worker="description_extraction_worker",
        event_type="job_description_extracted",
        worker_run_id=worker_run_id,
        metrics={
            "duration_ms": ai_duration,
            "model": "qwen2.5:7b-instruct",
            "json_valid": bool(extracted_data is not None)
        }
    )
    
    if extracted_data:
        print(f"  Successfully extracted description for Job ID {job_id}.")
        print("  Upserting to job_descriptions table...")
        insert_job_description(job_id, extracted_data)
        return True
    else:
        raise ValueError(f"AI returned None or empty data for Job ID {job_id}")

def extract_descriptions():
    worker_run_id = f"description-extraction-worker-{int(time.time())}"
    print(f"Starting description extraction worker. run_id={worker_run_id}")
    
    while True:
        fetch_record = None
        try:
            fetch_record = fetch_next_description_extraction_job()

            if not fetch_record:
                # No records ready for extraction, wait a bit
                print("No description jobs ready. Sleeping for 5 seconds...")
                time.sleep(5)
                continue
            
            # We have a lock on this record (status is 'description_extracting')
            fetch_id = fetch_record.get("id")
            
            try:
                process_description_extraction(fetch_record, worker_run_id)
                
                # Success
                update_job_page_fetch_status(fetch_id, "description_extracted")
                print(f"  Updated fetch {fetch_id} status to 'description_extracted'.")

            except LLMConnectionError as e:
                print(f"  Error processing fetch {fetch_id}: {e}")
                log_scrape_event(
                    scrape_id=fetch_id,
                    worker="description_extraction_worker",
                    event_type="scrape_failed",
                    severity="error",
                    worker_run_id=worker_run_id,
                    message=f"LLM connection error: {e}",
                    metrics={"error_message": str(e), "error_type": "llm_connection"}
                )
                update_job_page_fetch_status(fetch_id, "description_extraction_failed", str(e))
                print(f"  Updated fetch {fetch_id} status to 'description_extraction_failed'.")
                print("  LLM check failed. Sleeping 60 seconds before next run.")
                time.sleep(60)

            except Exception as e:
                print(f"  Error processing fetch {fetch_id}: {e}")
                log_scrape_event(
                    scrape_id=fetch_id,
                    worker="description_extraction_worker",
                    event_type="scrape_failed",
                    severity="error",
                    worker_run_id=worker_run_id,
                    message=f"Error processing description extraction: {e}",
                    metrics={"error_message": str(e), "error_type": "exception"}
                )
                update_job_page_fetch_status(fetch_id, "description_extraction_failed", str(e))
                print(f"  Updated fetch {fetch_id} status to 'description_extraction_failed'.")
                
        except Exception as e:
            # Global loop error handler
            print(f"Unexpected global error: {e}")
            if fetch_record and fetch_record.get("id"):
                fetch_id = fetch_record.get("id")
                log_scrape_event(
                    scrape_id=fetch_id,
                    worker="description_extraction_worker",
                    event_type="worker_error",
                    severity="error",
                    worker_run_id=worker_run_id,
                    message=f"Unexpected global error: {e}",
                    metrics={"error_message": str(e)}
                )
            time.sleep(5)

if __name__ == "__main__":
    extract_descriptions()
