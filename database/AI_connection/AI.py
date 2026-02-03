
import ollama
import json
from database.AI_connection.prompts import JOB_EXTRACTION_PROMPT
import time

MODEL = "qwen2.5:3b"

def extract_jobs_from_chunk(chunk):
    formatted_prompt = JOB_EXTRACTION_PROMPT.replace("{TEXT}", chunk)

    for attempt in range(2):
        if attempt == 1:
            time.sleep(0.3)
        try:
            res = ollama.chat(
                model=MODEL,
                messages=[{"role": "user", "content": formatted_prompt}],
                
            )

            raw = res["message"]["content"]
            # Basic cleanup if the model creates Markdown code blocks
            clean_json = raw.strip()
            if clean_json.startswith("```json"):
                clean_json = clean_json[7:]
            if clean_json.startswith("```"):
                clean_json = clean_json[3:]
            if clean_json.endswith("```"):
                clean_json = clean_json[:-3]
            
            # Remove control characters that might break JSON parsing
            # Keep newlines, tabs, and printable characters
            clean_json = "".join(ch for ch in clean_json if ch == '\n' or ch == '\t' or ch >= ' ')

            return json.loads(clean_json, strict=False)
        except Exception as e:
            print(f"Error extracting jobs from AI (attempt {attempt+1}/2): {e}")
            if attempt == 0:
                print("Retrying...")
    
    return []
