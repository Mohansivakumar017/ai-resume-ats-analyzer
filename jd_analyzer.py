import json
from pathlib import Path
from typing import Dict, Any
from ai_service import generate_json_content


def extract_jd(jd_text: str) -> Dict[str, Any]:
    """
    Extracts structured requirements from job description text using Gemini.
    """
    cleaned_text = (jd_text or "").strip()
    if not cleaned_text:
        raise ValueError("Job description cannot be empty.")

    prompt = f"""
Extract structured information from this job description.
Return ONLY valid JSON.
Do not invent information.

JSON format:
{{
    "job_title": "",
    "required_skills": [],
    "preferred_skills": [],
    "experience": {{
        "minimum_years": 0,
        "maximum_years": 0
    }},
    "education": [],
    "responsibilities": []
}}

Job Description:
{cleaned_text}
"""

    return generate_json_content(prompt)


if __name__ == "__main__":
    jd_file = Path(__file__).parent / "job_description.txt"
    if jd_file.is_file():
        with open(jd_file, "r", encoding="utf-8") as file:
            sample_jd = file.read()
        jd_data = extract_jd(sample_jd)
        print("Job Description Parsed Successfully:")
        print(json.dumps(jd_data, indent=2))
    else:
        print("job_description.txt not found for testing.")