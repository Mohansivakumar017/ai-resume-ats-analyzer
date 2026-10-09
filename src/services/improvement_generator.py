import json
import logging
from typing import Any, Dict, List
from src.services.gemini_service import gemini_service

logger = logging.getLogger(__name__)


def generate_resume_improvements(
    resume_data: Dict[str, Any],
    jd_data: Dict[str, Any],
    ats_score_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Generates actionable, specific resume improvements including bullet point
    rephrasing, metric quantification, and section optimization.
    """
    prompt = f"""
You are an executive resume coach and hiring manager.
Review this candidate's resume analysis against the target job description and provide targeted, high-impact improvements.

Candidate Profile:
{json.dumps(resume_data)}

Target Job Description:
{json.dumps(jd_data)}

ATS Score Findings:
{json.dumps(ats_score_data)}

Guidelines:
1. Do NOT invent fraudulent experience, companies, or degrees.
2. Provide concrete bullet-point improvements showing 'Before' vs 'After' examples with strong action verbs (e.g., 'Engineered', 'Orchestrated', 'Reduced', 'Architected').
3. Focus on quantifying project impact (e.g. latency, throughput, users, uptime, cost savings).
4. Give specific advice on integrating missing keywords naturally.

Return ONLY a valid JSON object matching this schema:
{{
    "key_strengths": ["string"],
    "critical_improvements": [
        {{
            "section": "string",
            "suggestion": "string",
            "example_transformation": "string"
        }}
    ],
    "ats_keyword_strategy": ["string"]
}}
"""

    return gemini_service.generate_json(
        prompt=prompt,
        system_instruction="You are an elite career strategist. Offer actionable, concrete advice that measurably boosts ATS rank."
    )
