
import ollama
import json
from database.AI_connection.prompts import JOB_EXTRACTION_PROMPT
import time
import requests
import subprocess
from urllib.parse import urlparse

MODEL = "qwen2.5:3b"
# MODEL = "qwen2.5:7b-instruct"

OLLAMA_URL = " http://192.168.1.248:11434/api/chat"


class LLMConnectionError(Exception):
    """Raised when the worker cannot reach the LLM server."""
    pass


def ensure_llm_server_available():
    parsed = urlparse(OLLAMA_URL.strip())
    if not parsed.scheme or not parsed.netloc:
        raise LLMConnectionError(f"Invalid OLLAMA_URL configured: {OLLAMA_URL!r}")

    tags_url = f"{parsed.scheme}://{parsed.netloc}/api/tags"
    result = subprocess.run(
        ["curl", "--silent", "--show-error", "--fail", "--max-time", "5", tags_url],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise LLMConnectionError(f"LLM connectivity check failed for {tags_url}: {stderr}")

def extract_jobs_from_chunk(chunk):
    formatted_prompt = JOB_EXTRACTION_PROMPT.replace("{TEXT}", chunk)

    for attempt in range(2):
        if attempt == 1:
            time.sleep(0.3)
        try:
            # res = ollama.chat(
            #     model=MODEL,
            #     messages=[{"role": "user", "content": formatted_prompt}],
                
            # )
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
            res = requests.post(OLLAMA_URL, json=payload)
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
    
    return []
