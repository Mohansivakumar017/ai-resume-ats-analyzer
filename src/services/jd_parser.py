import logging
from typing import Any, Dict
from src.services.gemini_service import gemini_service

logger = logging.getLogger(__name__)


def parse_job_description(jd_text: str) -> Dict[str, Any]:
    """
    Parses a job description to extract core qualifications, skills,
    experience benchmarks, and education requirements.
    """
    cleaned_text = (jd_text or "").strip()
    if len(cleaned_text) < 15:
        raise ValueError(
            "Job description is too short. Please provide a complete job posting."
        )

    prompt = f"""
You are an expert technical recruiter and ATS analyst.
Analyze the following job description and extract core hiring criteria.

Return ONLY a valid JSON object matching this schema:
{{
    "job_title": "string",
    "required_skills": ["string"],
    "preferred_skills": ["string"],
    "minimum_experience_years": 0.0,
    "required_education": [
        {{
            "level": "string",
            "field": "string"
        }}
    ],
    "key_responsibilities": ["string"],
    "keywords": ["string"]
}}

Job Description:
{cleaned_text}
"""

    return gemini_service.generate_json(
        prompt=prompt,
        system_instruction="You are an expert talent acquisition analyzer. Separate mandatory criteria from optional nice-to-have qualifications."
    )
