import re
from typing import Dict, Any, List, Set, Tuple


SKILL_ALIASES = {
    "amazon web services": "aws",
    "aws": "aws",
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "js": "javascript",
    "javascript": "javascript",
    "ts": "typescript",
    "typescript": "typescript",
    "node": "node.js",
    "nodejs": "node.js",
    "node.js": "node.js",
    "react": "react.js",
    "reactjs": "react.js",
    "react.js": "react.js",
    "k8s": "kubernetes",
    "kubernetes": "kubernetes",
    "ci/cd": "ci/cd",
    "cicd": "ci/cd",
    "continuous integration": "ci/cd",
    "docker": "docker",
    "gcp": "google cloud",
    "google cloud platform": "google cloud",
    "golang": "go",
    "go": "go",
    "python": "python",
    "fastapi": "fastapi",
    "flask": "flask",
    "django": "django",
    "sql": "sql",
    "nosql": "nosql",
    "redis": "redis",
    "kafka": "kafka",
    "git": "git",
    "github": "git",
    "linux": "linux",
}


def normalize_skill(skill: str) -> str:
    """Normalize skill name to standard lowercase form using aliases."""
    cleaned = (skill or "").lower().strip()
    return SKILL_ALIASES.get(cleaned, cleaned)


def skill_present_in_text(skill: str, text: str) -> bool:
    """
    Check if a skill is present in text using word boundaries to avoid
    false positives for short skill names (e.g., 'c', 'r', 'go').
    """
    if not skill or not text:
        return False

    pattern = r"(?:\b|_)" + re.escape(skill) + r"(?:\b|_)"
    return bool(re.search(pattern, text, re.IGNORECASE))


def calculate_skill_match(
    resume_skills: List[str],
    jd_skills: List[str],
    resume_text: str = ""
) -> Tuple[Set[str], Set[str]]:
    """
    Matches JD skills against resume structured skills and raw resume text.
    Handles compound/alternative skills (e.g., 'FastAPI or Flask', 'PostgreSQL / MySQL').
    """
    resume_normalized = {
        normalize_skill(skill)
        for skill in (resume_skills or [])
        if skill
    }

    matched = set()
    missing = set()

    for skill in (jd_skills or []):
        if not skill:
            continue

        normalized = normalize_skill(skill)
        alternatives = [
            s.strip()
            for s in re.split(r"\s+or\s+|\s*/\s*", skill, flags=re.IGNORECASE)
            if s.strip()
        ]

        if len(alternatives) > 1:
            found_alt = False
            for alt in alternatives:
                norm_alt = normalize_skill(alt)
                if (
                    norm_alt in resume_normalized
                    or skill_present_in_text(alt, resume_text)
                    or skill_present_in_text(norm_alt, resume_text)
                ):
                    matched.add(norm_alt)
                    found_alt = True
                    break
            if not found_alt:
                missing.add(normalized)
        else:
            if (
                normalized in resume_normalized
                or skill_present_in_text(skill, resume_text)
                or skill_present_in_text(normalized, resume_text)
            ):
                matched.add(normalized)
            else:
                missing.add(normalized)

    return matched, missing


def calculate_education_score(resume_data: Dict[str, Any], jd_data: Dict[str, Any]) -> int:
    """Calculate education score out of 10 points."""
    resume_education = str(resume_data.get("education", [])).lower()
    jd_education = str(jd_data.get("education", [])).lower()

    degree_keywords = [
        "bachelor", "b.tech", "btech", "b.e", "be",
        "master", "m.tech", "mtech", "m.e", "me", "phd", "degree"
    ]

    field_keywords = [
        "computer science", "information technology",
        "software engineering", "data science", "information systems"
    ]

    has_degree = any(kw in resume_education for kw in degree_keywords)

    # Check matching field or open field requirements
    no_strict_jd_field = not jd_education or jd_education == "[]" or "related field" in jd_education or "any" in jd_education
    has_matching_field = any(
        kw in resume_education and (kw in jd_education or no_strict_jd_field)
        for kw in field_keywords
    )

    if has_degree and (has_matching_field or no_strict_jd_field):
        return 10
    if has_degree:
        return 7
    if resume_education and resume_education != "[]":
        return 5

    return 0


def calculate_structure_score(resume_data: Dict[str, Any]) -> int:
    """Calculates structure score based on standard resume sections (up to 10 points)."""
    score = 0
    sections = {
        "skills": 2,
        "education": 2,
        "experience": 2,
        "projects": 2,
        "certifications": 2,
    }

    for section, points in sections.items():
        val = resume_data.get(section)
        if val and (isinstance(val, list) and len(val) > 0 or isinstance(val, dict) and len(val) > 0 or isinstance(val, str) and val.strip()):
            score += points

    return score


def calculate_keyword_score(resume_text: str, jd_data: Dict[str, Any]) -> int:
    """Calculates keyword presence in resume text out of 10 points."""
    keywords = set()
    raw_skills = (jd_data.get("required_skills", []) or []) + (jd_data.get("preferred_skills", []) or [])
    for skill in raw_skills:
        if not skill:
            continue
        alternatives = [
            s.strip().lower()
            for s in re.split(r"\s+or\s+|\s*/\s*", skill, flags=re.IGNORECASE)
            if s.strip()
        ]
        for alt in alternatives:
            keywords.add(alt)

    if not keywords:
        return 10

    matched = sum(1 for kw in keywords if skill_present_in_text(kw, resume_text))
    return round((matched / len(keywords)) * 10)


def extract_min_years_from_jd(jd_experience: Any) -> float:
    """Safely extracts minimum years required from various JD formats."""
    if isinstance(jd_experience, dict):
        val = jd_experience.get("minimum_years", 0)
        try:
            return float(val or 0)
        except (ValueError, TypeError):
            return 0.0
    elif isinstance(jd_experience, (int, float)):
        return float(jd_experience)
    elif isinstance(jd_experience, str):
        matches = re.findall(r"(\d+(?:\.\d+)?)", jd_experience)
        if matches:
            return float(matches[0])
    return 0.0


def extract_total_resume_years(resume_experience: Any) -> float:
    """Calculates total experience years from structured resume experience."""
    if not isinstance(resume_experience, list):
        return 0.0

    total_years = 0.0
    for exp in resume_experience:
        if isinstance(exp, dict):
            years = exp.get("years", 0)
            if isinstance(years, (int, float)):
                total_years += float(years)
            elif isinstance(years, str):
                match = re.search(r"(\d+(?:\.\d+)?)", years)
                if match:
                    total_years += float(match.group(1))
            else:
                # If experience entry exists without explicit years, assume at least 1 year project/internship
                total_years += 1.0
        elif isinstance(exp, str) and exp.strip():
            total_years += 1.0

    return total_years


def calculate_ats_score(
    resume_data: Dict[str, Any],
    jd_data: Dict[str, Any],
    resume_text: str
) -> Dict[str, Any]:
    """
    Computes overall ATS score and detailed breakdown across:
    - Required Skills: 40 points
    - Preferred Skills: 15 points
    - Experience: 15 points
    - Education: 10 points
    - Structure: 10 points
    - Keyword Coverage: 10 points
    Total: 100 points
    """
    resume_skills = resume_data.get("skills", [])
    required_skills = jd_data.get("required_skills", [])
    preferred_skills = jd_data.get("preferred_skills", [])

    # 1. Required skills (40 points)
    req_matched, req_missing = calculate_skill_match(
        resume_skills, required_skills, resume_text
    )
    if required_skills:
        req_score = (len(req_matched) / len(required_skills)) * 40
    else:
        req_score = 40.0

    # 2. Preferred skills (15 points)
    pref_matched, pref_missing = calculate_skill_match(
        resume_skills, preferred_skills, resume_text
    )
    if preferred_skills:
        pref_score = (len(pref_matched) / len(preferred_skills)) * 15
    else:
        pref_score = 15.0

    # 3. Education (10 points)
    education_score = calculate_education_score(resume_data, jd_data)

    # 4. Experience (15 points)
    resume_exp = resume_data.get("experience", [])
    jd_exp = jd_data.get("experience", {})
    req_years = extract_min_years_from_jd(jd_exp)
    cand_years = extract_total_resume_years(resume_exp)

    if cand_years > 0:
        if req_years == 0 or cand_years >= req_years:
            experience_score = 15
        elif cand_years >= (req_years * 0.5):
            experience_score = 10
        else:
            experience_score = 7
    elif req_years == 0:
        # Fresher friendly role and candidate has projects
        if resume_data.get("projects"):
            experience_score = 12
        else:
            experience_score = 5
    else:
        experience_score = 0

    # 5. Structure (10 points)
    structure_score = calculate_structure_score(resume_data)

    # 6. Keyword Coverage (10 points)
    keyword_score = calculate_keyword_score(resume_text, jd_data)

    total_score = (
        req_score
        + pref_score
        + experience_score
        + education_score
        + structure_score
        + keyword_score
    )

    return {
        "score": max(0, min(100, round(total_score))),
        "required_skill_score": round(req_score, 1),
        "preferred_skill_score": round(pref_score, 1),
        "experience_score": experience_score,
        "education_score": education_score,
        "structure_score": structure_score,
        "keyword_score": keyword_score,
        "matched_required": sorted(list(req_matched)),
        "missing_required": sorted(list(req_missing)),
        "matched_preferred": sorted(list(pref_matched)),
        "missing_preferred": sorted(list(pref_missing)),
    }