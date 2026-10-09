import json
import logging
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.config import config
from src.services.gemini_service import gemini_service

logger = logging.getLogger(__name__)


def load_curated_courses() -> List[Dict[str, Any]]:
    """Loads curated course catalog from data directory."""
    path = config.CURATED_COURSES_PATH
    if not path.is_file():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("Could not read curated courses: %s", exc)
        return []


def recommend_learning_paths(
    missing_required: List[str],
    missing_preferred: List[str],
    job_title: str = "Target Role"
) -> List[Dict[str, Any]]:
    """
    Combines curated learning databases with AI-powered course generation
    to give comprehensive learning roadmaps for all skill gaps.
    """
    curated = load_curated_courses()
    curated_map = {c["skill"].lower().strip(): c for c in curated}

    recommendations = []
    unmapped_skills = []

    # 1. Match against curated library
    all_missing = [(s, "HIGH") for s in missing_required] + [
        (s, "MEDIUM") for s in missing_preferred
    ]

    for skill, priority in all_missing:
        cleaned = skill.lower().strip()
        if cleaned in curated_map:
            item = curated_map[cleaned].copy()
            item["priority"] = priority
            item["reason"] = (
                f"Essential skill required for {job_title}"
                if priority == "HIGH"
                else f"Preferred bonus skill for {job_title}"
            )
            recommendations.append(item)
        else:
            unmapped_skills.append((skill, priority))

    # 2. If there are unmapped skills, synthesize tailored recommendations using Gemini
    if unmapped_skills:
        skill_names = [s[0] for s in unmapped_skills]
        prompt = f"""
For the following missing skills required for the role of '{job_title}', recommend top-tier, legitimate online learning resources (e.g., freeCodeCamp, Coursera, official documentation, edX, or YouTube).

Skills to cover: {json.dumps(skill_names)}

Return ONLY valid JSON matching this schema:
[
    {{
        "skill": "string",
        "course": "string (specific course or tutorial title)",
        "platform": "string (e.g. Coursera, freeCodeCamp, Official Docs)",
        "url": "string (realistic or official search/tutorial link)",
        "level": "string (Beginner / Intermediate / Advanced)"
    }}
]
"""
        try:
            ai_recs = gemini_service.generate_json(prompt)
            if isinstance(ai_recs, list):
                priority_map = {s[0].lower(): s[1] for s in unmapped_skills}
                for rec in ai_recs:
                    sk = rec.get("skill", "").lower()
                    rec["priority"] = priority_map.get(sk, "MEDIUM")
                    rec["reason"] = f"Key skill to bridge qualifications gap for {job_title}"
                    recommendations.append(rec)
        except Exception as exc:
            logger.warning("Dynamic course generation fallback triggered: %s", exc)
            for skill, priority in unmapped_skills:
                encoded = urllib.parse.quote_plus(skill)
                recommendations.append({
                    "skill": skill,
                    "course": f"{skill.title()} Practical Foundations",
                    "platform": "freeCodeCamp / Official Docs",
                    "url": f"https://www.google.com/search?q={encoded}+getting+started+tutorial",
                    "level": "All Levels",
                    "priority": priority,
                    "reason": f"Skill needed for {job_title}",
                })

    return recommendations
