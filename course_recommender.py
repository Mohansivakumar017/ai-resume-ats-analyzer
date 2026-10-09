import json
from pathlib import Path
from typing import List, Dict, Any, Optional
import urllib.parse


def load_courses() -> List[Dict[str, Any]]:
    """Loads course database from courses.json relative to current file."""
    courses_file = Path(__file__).parent / "courses.json"
    if not courses_file.is_file():
        return []

    try:
        with open(courses_file, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return []


def recommend_courses(
    missing_required: Optional[List[str]] = None,
    missing_preferred: Optional[List[str]] = None,
    missing_skills: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """
    Recommends tailored courses based on detected skill gaps.
    Supports either:
      - recommend_courses(missing_required, missing_preferred)
      - recommend_courses(missing_skills)
    """
    all_courses = load_courses()
    course_map = {c["skill"].lower().strip(): c for c in all_courses}

    req_set = set()
    if missing_required:
        req_set = {s.lower().strip() for s in missing_required if s}

    pref_set = set()
    if missing_preferred:
        pref_set = {s.lower().strip() for s in missing_preferred if s}

    # Handle single missing_skills list argument
    if missing_skills:
        for s in missing_skills:
            if s:
                req_set.add(s.lower().strip())

    recommendations = []
    seen_skills = set()

    # 1. Process required skills (HIGH priority)
    for skill in sorted(req_set):
        if skill in seen_skills:
            continue
        seen_skills.add(skill)

        if skill in course_map:
            rec = course_map[skill].copy()
            rec["priority"] = "HIGH"
            rec["reason"] = f"Required skill '{skill.title()}' missing from resume"
            recommendations.append(rec)
        else:
            # Fallback search course
            encoded = urllib.parse.quote_plus(skill)
            recommendations.append({
                "skill": skill,
                "course": f"{skill.title()} Masterclass & Practical Guide",
                "platform": "freeCodeCamp / YouTube",
                "priority": "HIGH",
                "reason": f"Required skill '{skill.title()}' missing from resume",
                "url": f"https://www.youtube.com/results?search_query={encoded}+tutorial+full+course"
            })

    # 2. Process preferred skills (MEDIUM priority)
    for skill in sorted(pref_set):
        if skill in seen_skills:
            continue
        seen_skills.add(skill)

        if skill in course_map:
            rec = course_map[skill].copy()
            rec["priority"] = "MEDIUM"
            rec["reason"] = f"Preferred skill '{skill.title()}' (bonus qualification)"
            recommendations.append(rec)
        else:
            encoded = urllib.parse.quote_plus(skill)
            recommendations.append({
                "skill": skill,
                "course": f"{skill.title()} Practical Foundations",
                "platform": "freeCodeCamp / Docs",
                "priority": "MEDIUM",
                "reason": f"Preferred skill '{skill.title()}' (bonus qualification)",
                "url": f"https://www.google.com/search?q={encoded}+getting+started+tutorial"
            })

    return recommendations