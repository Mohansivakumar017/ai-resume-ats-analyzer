import re
import logging
from typing import Any, Dict, List, Set, Tuple
from src.config import config

logger = logging.getLogger(__name__)


def clean_skill(skill: str) -> str:
    """Normalize skill string by removing excessive punctuation and whitespace."""
    if not skill:
        return ""
    cleaned = skill.lower().strip()
    # Normalize common abbreviations
    cleaned = re.sub(r"\bjs\b", "javascript", cleaned)
    cleaned = re.sub(r"\bts\b", "typescript", cleaned)
    cleaned = re.sub(r"\bk8s\b", "kubernetes", cleaned)
    cleaned = re.sub(r"\bpostgres\b", "postgresql", cleaned)
    cleaned = re.sub(r"\baws\b", "amazon web services", cleaned)
    cleaned = re.sub(r"\bgcp\b", "google cloud platform", cleaned)
    return cleaned


def is_skill_in_text(skill: str, text: str) -> bool:
    """Check presence using word boundaries to prevent substring false-positives."""
    if not skill or not text:
        return False
    # Escape regex symbols but preserve word boundaries
    pattern = r"(?:\b|_)" + re.escape(skill) + r"(?:\b|_)"
    return bool(re.search(pattern, text, re.IGNORECASE))


def match_skills(
    candidate_skills: List[str],
    target_skills: List[str],
    resume_text: str = ""
) -> Tuple[Set[str], Set[str]]:
    """
    Matches target skills against candidate skills and full resume text.
    Handles compound requirements (e.g., 'FastAPI or Flask', 'PostgreSQL / MySQL').
    """
    normalized_candidate = {clean_skill(s) for s in candidate_skills if s}
    matched = set()
    missing = set()

    for raw_target in target_skills:
        if not raw_target:
            continue

        # Split compound skills separated by 'or', '/', or '|'
        alternatives = [
            s.strip()
            for s in re.split(r"\s+or\s+|\s*[/|]\s*", raw_target, flags=re.IGNORECASE)
            if s.strip()
        ]

        found = False
        for alt in alternatives:
            cleaned_alt = clean_skill(alt)
            if (
                cleaned_alt in normalized_candidate
                or is_skill_in_text(alt, resume_text)
                or is_skill_in_text(cleaned_alt, resume_text)
            ):
                matched.add(cleaned_alt)
                found = True
                break

        if not found:
            missing.add(clean_skill(raw_target))

    return matched, missing


def score_experience(candidate_experience: List[Dict[str, Any]], min_required_years: float) -> Tuple[float, float]:
    """
    Calculates total candidate experience and computes experience score.
    """
    total_years = 0.0
    for exp in candidate_experience or []:
        if isinstance(exp, dict):
            yrs = exp.get("years", 0.0)
            if isinstance(yrs, (int, float)):
                total_years += float(yrs)
            elif isinstance(yrs, str):
                nums = re.findall(r"(\d+(?:\.\d+)?)", yrs)
                if nums:
                    total_years += float(nums[0])
                else:
                    total_years += 1.0
            else:
                total_years += 1.0
        elif isinstance(exp, str) and exp.strip():
            total_years += 1.0

    if min_required_years <= 0:
        score = config.WEIGHT_EXPERIENCE if total_years > 0 else (config.WEIGHT_EXPERIENCE * 0.8)
    else:
        ratio = min(1.0, total_years / min_required_years)
        score = config.WEIGHT_EXPERIENCE * ratio

    return round(score, 1), round(total_years, 1)


def score_education(candidate_education: List[Dict[str, Any]], jd_education: List[Dict[str, Any]]) -> float:
    """
    Scores education dynamically based on whether candidate degrees match
    the level and domain requested in the job description.
    """
    if not candidate_education:
        return config.WEIGHT_EDUCATION * 0.3

    if not jd_education:
        # No strict educational mandate in JD, candidate has degree
        return config.WEIGHT_EDUCATION

    # Check for matching degree level or field
    cand_fields = []
    cand_degrees = []
    for item in candidate_education:
        if isinstance(item, dict):
            cand_degrees.append(str(item.get("degree", "")).lower())
            cand_fields.append(str(item.get("field", "")).lower())
        elif isinstance(item, str):
            cand_degrees.append(item.lower())

    cand_text = " ".join(cand_degrees + cand_fields)

    matched_criteria = 0
    for req in jd_education:
        if isinstance(req, dict):
            level = str(req.get("level", "")).lower()
            field = str(req.get("field", "")).lower()
            if level and level in cand_text:
                matched_criteria += 1
            if field and (field in cand_text or "related" in field or "any" in field):
                matched_criteria += 1
        elif isinstance(req, str):
            if req.lower() in cand_text:
                matched_criteria += 1

    if matched_criteria > 0:
        return config.WEIGHT_EDUCATION
    return config.WEIGHT_EDUCATION * 0.7


def score_resume_structure(resume_data: Dict[str, Any]) -> float:
    """
    Checks for essential sections in the resume (Skills, Experience, Education, Projects, Certifications).
    """
    essential_sections = ["skills", "experience", "education", "projects", "certifications"]
    present_count = 0
    for sec in essential_sections:
        val = resume_data.get(sec)
        if val and (isinstance(val, list) and len(val) > 0 or isinstance(val, dict) or isinstance(val, str)):
            present_count += 1

    ratio = present_count / len(essential_sections)
    return round(config.WEIGHT_STRUCTURE * ratio, 1)


def score_keywords(resume_text: str, jd_keywords: List[str]) -> Tuple[float, int, int]:
    """
    Scores industry keyword coverage against resume text.
    """
    if not jd_keywords:
        return config.WEIGHT_KEYWORDS, 0, 0

    unique_keywords = {k.strip().lower() for k in jd_keywords if k and k.strip()}
    if not unique_keywords:
        return config.WEIGHT_KEYWORDS, 0, 0

    matched = sum(1 for kw in unique_keywords if is_skill_in_text(kw, resume_text))
    score = round((matched / len(unique_keywords)) * config.WEIGHT_KEYWORDS, 1)
    return score, matched, len(unique_keywords)


def evaluate_ats_fit(
    resume_data: Dict[str, Any],
    jd_data: Dict[str, Any],
    resume_text: str
) -> Dict[str, Any]:
    """
    Performs comprehensive ATS scoring across 6 weighted dimensions:
    1. Required Skills Match
    2. Preferred Skills Match
    3. Experience Relevance & Tenure
    4. Education & Field Relevance
    5. Structural Section Completeness
    6. Keyword Density & Relevance
    """
    # 1. Required Skills
    req_skills = jd_data.get("required_skills", [])
    cand_skills = resume_data.get("skills", [])
    matched_req, missing_req = match_skills(cand_skills, req_skills, resume_text)
    req_score = (
        config.WEIGHT_REQUIRED_SKILLS
        if not req_skills
        else round((len(matched_req) / len(req_skills)) * config.WEIGHT_REQUIRED_SKILLS, 1)
    )

    # 2. Preferred Skills
    pref_skills = jd_data.get("preferred_skills", [])
    matched_pref, missing_pref = match_skills(cand_skills, pref_skills, resume_text)
    pref_score = (
        config.WEIGHT_PREFERRED_SKILLS
        if not pref_skills
        else round((len(matched_pref) / len(pref_skills)) * config.WEIGHT_PREFERRED_SKILLS, 1)
    )

    # 3. Experience
    min_years = float(jd_data.get("minimum_experience_years", 0.0) or 0.0)
    exp_score, total_years = score_experience(resume_data.get("experience", []), min_years)

    # 4. Education
    edu_score = score_education(
        resume_data.get("education", []),
        jd_data.get("required_education", [])
    )

    # 5. Structure
    struct_score = score_resume_structure(resume_data)

    # 6. Keywords
    kw_list = jd_data.get("keywords", []) or (req_skills + pref_skills)
    kw_score, kw_matched_count, kw_total_count = score_keywords(resume_text, kw_list)

    # Total Score calculation
    total_score = round(
        req_score + pref_score + exp_score + edu_score + struct_score + kw_score
    )
    final_score = max(0, min(100, total_score))

    return {
        "overall_score": final_score,
        "breakdown": {
            "required_skills": {"score": req_score, "max": config.WEIGHT_REQUIRED_SKILLS},
            "preferred_skills": {"score": pref_score, "max": config.WEIGHT_PREFERRED_SKILLS},
            "experience": {"score": exp_score, "max": config.WEIGHT_EXPERIENCE, "detected_years": total_years},
            "education": {"score": edu_score, "max": config.WEIGHT_EDUCATION},
            "structure": {"score": struct_score, "max": config.WEIGHT_STRUCTURE},
            "keywords": {"score": kw_score, "max": config.WEIGHT_KEYWORDS, "matched": kw_matched_count, "total": kw_total_count},
        },
        "matched_required": sorted(list(matched_req)),
        "missing_required": sorted(list(missing_req)),
        "matched_preferred": sorted(list(matched_pref)),
        "missing_preferred": sorted(list(missing_pref)),
    }
