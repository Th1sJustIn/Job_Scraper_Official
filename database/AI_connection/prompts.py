# JOB_EXTRACTION_PROMPT = """
# You are a structured data extraction engine.

# Extract ONLY information that explicitly appears in the provided text.
# Do NOT infer, guess, or hallucinate.
# If a field is missing, return null.

# Return ONLY valid JSON.
# Return a SINGLE FLAT JSON ARRAY of objects.

# Each object must follow EXACTLY this schema:

# {
#   "department": string or null,
#   "title": string,
#   "location": string or null,
#   "job_url": string
# }

# RULES:
# - Output must be one flat array (NO nested arrays)
# - Do NOT group jobs by department
# - Each job must be its own object
# - Use the exact job title text
# - Use the exact location text
# - Use the full job link
# - If any value is missing, use null
# - Do NOT include explanations, markdown, or extra text

# If no jobs exist, return [].

# Here is the text:

# {TEXT}
# """


JOB_EXTRACTION_PROMPT = """
You are a strict JSON extraction engine.

Return ONLY valid JSON (no markdown, no comments, no extra text).
Return a FLAT array of job objects. Never return nested arrays.

Extract job listings that explicitly appear in the text.

Schema:
[
  {
    "department": string|null,
    "title": string,
    "location": string|null,
    "job_url": string
  }
]

Rules:
- "title" must be plain text ONLY. If you see markdown like: [Some Title](https://example.com),
  then title = "Some Title" and job_url = "https://example.com".
- "job_url" must be a raw URL string only (no markdown, no "Apply", no brackets).
- Ignore generic links like "Instacart Shopper" / "Start here" unless clearly listed as a job opening.
- If department is not explicitly stated near the job, use null.
- If location is missing, use null.
- If no jobs appear, return [].

Important exclusions (DO NOT extract as jobs):

- Do NOT extract department/category links such as:
  Engineering, Marketing, Sales, Finance, etc.
- Do NOT extract navigation or filter buttons.
- Do NOT extract links whose URL starts with "#" (anchors like #jobs).
- A valid job must represent a specific role (e.g. "Senior Data Engineer", not "Engineering").

Only extract actual open positions with specific role titles.

TEXT:
{TEXT}
"""