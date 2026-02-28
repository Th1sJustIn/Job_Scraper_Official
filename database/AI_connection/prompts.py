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

JOB_DESCRIPTION_EXTRACTION_PROMPT = """
You are a structured job description extraction engine.

Extract ONLY information that appears in the provided markdown.
Do NOT hallucinate or guess items completely not supported by the text.
However, you MUST intelligently categorize information according to standard job descriptions.
If a field is truly missing, return null.
Return valid JSON only. Do not include explanations.

IMPORTANT:
- Do NOT extract title, location, department, or URL.
- Use concise summaries.
- Normalize numeric values where required.

Return a single JSON object using this schema:

{
  "responsibilities": string[] or [],
  "requirements": string[] or [],
  "preferred_requirements": string[] or [],
  "tech_stack": string[] or [],

  "experience_level": "intern" | "new_grad" | "entry" | "mid" | "senior" | "staff" | "unknown",
  "is_entry_level": boolean,

  "years_experience": {
    "min": number or null,
    "max": number or null
  },

  "employment_type": "full_time" | "internship" | "contract" | "unknown",
  "internship": boolean,

  "salary_range": {
    "min": number or null,
    "max": number or null,
    "currency": string or null
  },

  "visa_sponsorship": true | false | null,
  "remote_policy": "remote" | "hybrid" | "onsite" | "unknown",
  "team": string or null,
  "degree_required": true | false | null
}

Rules for specific fields:

RESPONSIBILITIES:
- Extract bullet points under sections like “What you’ll do”, "Your Role", or similar.

REQUIREMENTS:
- Extract qualifications and skills required for the role.

PREFERRED_REQUIREMENTS:
- Extract items labeled preferred, nice-to-have, bonus, or "plus".

TECH_STACK:
- Extract technologies mentioned ANYWHERE in the text (languages, frameworks, tools, cloud, databases) including inside the "bonus" or "preferred" sections.
- Return clean names only (e.g., "Python", "React", "AWS", "Rust", "Go").

EXPERIENCE_LEVEL:
- Use your best judgment based on the responsibilities, title prefix (if present in text), or years required.
- "intern" if explicitly internship.
- "new_grad" if explicitly new grad or graduate program.
- "entry" if 0–2 years, junior, early career.
- "mid" if 2–5 years, or general "Software Engineer" with previous experience required.
- "senior" if senior, 5+ years, lead.
- "staff" if staff/principal level.
- Otherwise "unknown".

IS_ENTRY_LEVEL:
- true if internship, new grad, junior, early career, or <=3 years required.
- false otherwise.

YEARS_EXPERIENCE:
- Extract numeric min/max from phrases like "3+ years", "2-5 years".
- If only minimum is given (e.g., "3+ years"), set max to null.
- If none stated, both null.

EMPLOYMENT_TYPE:
- Determine from text (full-time, internship, contract).
- If unclear, return "unknown".

INTERNSHIP:
- true only if explicitly internship.

SALARY_RANGE:
- Extract numeric salary values if present.
- Convert ranges like "$120k-$150k" to numbers (120000, 150000).
- If only one number is given, set min and max equal.
- If not present, return nulls.

VISA_SPONSORSHIP:
- true if explicitly offers sponsorship.
- false if explicitly does NOT sponsor.
- null if not mentioned.

REMOTE_POLICY:
- "remote" if fully remote.
- "hybrid" if hybrid.
- "onsite" if explicitly onsite.
- "unknown" if unclear.

TEAM:
- Extract team/org if explicitly mentioned (e.g., "Platform Team", "AI Team").

DEGREE_REQUIRED:
- true if degree explicitly required.
- false if explicitly states degree not required.
- null if not mentioned.

If the description is not a job or lacks required information, return null for all fields.

Here is the markdown:

{TEXT}
"""