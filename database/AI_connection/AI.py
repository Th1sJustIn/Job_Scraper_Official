
import ollama
import json
from database.AI_connection.prompts import JOB_EXTRACTION_PROMPT
import time
import requests

MODEL = "qwen2.5:3b"
# MODEL = "qwen2.5:7b-instruct"

OLLAMA_URL = " http://192.168.1.248:11434/api/chat"

def extract_jobs_from_chunk(chunk):
    formatted_prompt = JOB_EXTRACTION_PROMPT.replace("{TEXT}", chunk)
    request_error = None

    for attempt in range(2):
        if attempt == 1:
            time.sleep(0.3)
        payload = {
            "model": MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": formatted_prompt
                }
            ],
            "stream": False,
            "options": {
                "temperature": 0.1
            }
        }
        try:
            # res = ollama.chat(
            #     model=MODEL,
            #     messages=[{"role": "user", "content": formatted_prompt}],
            # )
            res = requests.post(OLLAMA_URL, json=payload, timeout=30)
            res.raise_for_status()
        except requests.RequestException as e:
            request_error = e
            print(f"Error reaching AI server (attempt {attempt+1}/2): {e}")
            if attempt == 0:
                print("Retrying...")
            continue

        try:
            raw = res.json()["message"]["content"]
            print(raw)
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
    
    if request_error is not None:
        raise ConnectionError(f"Unable to reach AI server after retries: {request_error}") from request_error

    return []
