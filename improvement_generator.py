import json
from typing import Dict, Any
from ai_service import generate_json_content


def generate_improvements(
    resume_data: Dict[str, Any],
    jd_data: Dict[str, Any],
    ats_result: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Generates actionable resume improvements and strengths based on ATS analysis.
    """
    prompt = f"""
You are a professional resume improvement assistant.
Analyze the resume against the job description and ATS findings.

Return ONLY valid JSON.
Do NOT invent experience, skills, projects, achievements, certifications, or numbers.
Only recommend improvements based on information already present in the resume.

Return exactly this structure:
{{
    "strengths": [],
    "missing_skills": [],
    "improvements": []
}}

Resume:
{json.dumps(resume_data)}

Job Description:
{json.dumps(jd_data)}

ATS Analysis:
{json.dumps(ats_result)}

For improvements:
- Give practical, high-impact resume improvements (formatting, bullet point framing, action verbs).
- Prioritize missing or weak areas.
- If a skill is genuinely missing, advise candidate to learn it rather than fabricating it.
- Keep improvements concise, constructive, and directly applicable.
"""

    return generate_json_content(prompt)