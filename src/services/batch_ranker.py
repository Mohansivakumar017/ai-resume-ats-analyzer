import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from src.services.resume_parser import parse_resume
from src.services.jd_parser import parse_job_description
from src.services.ats_scorer import evaluate_ats_fit

logger = logging.getLogger(__name__)


def extract_candidate_name(resume_data: Dict[str, Any], resume_text: str, filename: str) -> str:
    """Extracts or infers candidate name with multi-stage fallback, ignoring temp filenames."""
    # 1. First priority: Name extracted directly by Gemini AI
    extracted_name = (resume_data.get("candidate_name") or "").strip()
    if (
        extracted_name
        and len(extracted_name) > 2
        and not any(bad in extracted_name.lower() for bad in ["unknown", "string", "candidate", "n/a", "resume", "none", "null"])
    ):
        return extracted_name.title()

    # 2. Second priority: Top 3 lines of resume text
    lines = [line.strip() for line in resume_text.split("\n") if line.strip()]
    for line in lines[:3]:
        words = line.split()
        if 2 <= len(words) <= 4 and all(re.match(r"^[A-Za-z.\-']+$", w) for w in words):
            lower_line = line.lower()
            if not any(kw in lower_line for kw in ["resume", "curriculum", "vitae", "summary", "profile", "contact", "email", "phone", "developer", "engineer", "software", "skills", "experience"]):
                return line.title()

    # 3. Third priority: Check contact email prefix if sensible
    contact = resume_data.get("contact", {}) or {}
    email = (contact.get("email") or "").strip()
    if email and "@" in email:
        prefix = email.split("@")[0]
        cleaned_prefix = re.sub(r"[0-9_\.\-]+", " ", prefix).strip()
        parts = cleaned_prefix.split()
        if 1 <= len(parts) <= 3 and all(len(p) > 1 for p in parts):
            return cleaned_prefix.title()

    # 4. Fourth priority: Clean original filename (ONLY if NOT a temp file)
    stem = Path(filename).stem
    is_temp = stem.lower().startswith("tmp") or bool(re.match(r"^[a-f0-9\-_]{8,}$", stem.lower()))
    if not is_temp:
        stem = re.sub(r"(sample|candidate|resume|cv|_|-)", " ", stem, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", stem).strip().title()
        if cleaned and len(cleaned) > 2:
            return cleaned

    return "Candidate"


def normalize_resume_inputs(
    resumes: List[Union[str, Path, Dict[str, Any]]]
) -> List[Dict[str, str]]:
    """Normalizes various input formats into a list of dicts with 'path' and 'name'."""
    normalized = []
    for item in resumes:
        if isinstance(item, dict):
            p = str(item.get("path", ""))
            n = str(item.get("name") or item.get("original_name") or Path(p).name)
            normalized.append({"path": p, "name": n})
        elif isinstance(item, (str, Path)):
            p = str(item)
            normalized.append({"path": p, "name": Path(p).name})
    return normalized


def rank_resumes(
    resumes: List[Union[str, Path, Dict[str, Any]]],
    jd_text: str,
    jd_data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Evaluates multiple candidate resumes against a single job description,
    ranks them on an objective ATS leaderboard, and identifies the best candidate.
    Preserves actual uploaded file names and candidate contact information.
    """
    normalized_resumes = normalize_resume_inputs(resumes)
    if not normalized_resumes:
        raise ValueError("At least one valid resume must be provided for ranking.")

    # 1. Parse Job Description
    if not jd_data:
        jd_data = parse_job_description(jd_text)

    target_role = jd_data.get("job_title", "Target Role")
    total_candidates = len(normalized_resumes)
    evaluations = []

    logger.info("Ranking %d resumes for role '%s'", total_candidates, target_role)

    # 2. Evaluate each candidate resume
    for item in normalized_resumes:
        path = item["path"]
        display_name = item["name"]

        try:
            resume_text, resume_data = parse_resume(path)
            ats_result = evaluate_ats_fit(resume_data, jd_data, resume_text)
            cand_name = extract_candidate_name(resume_data, resume_text, display_name)

            score = ats_result["overall_score"]
            bd = ats_result["breakdown"]

            if score >= 85:
                status = "🌟 Top Tier Match"
                recommendation = "Strongly Recommended (Fast-Track)"
            elif score >= 70:
                status = "🟢 Strong Fit"
                recommendation = "Recommended for Interview"
            elif score >= 50:
                status = "🟡 Moderate Fit"
                recommendation = "Conditional Match (Review Skill Gaps)"
            else:
                status = "🔴 Low Fit"
                recommendation = "Not Recommended for this Role"

            contact = resume_data.get("contact", {})
            evaluations.append({
                "candidate_name": cand_name,
                "filename": display_name,
                "file_path": path,
                "score": score,
                "breakdown": bd,
                "status": status,
                "recommendation": recommendation,
                "contact": contact,
                "matched_required": ats_result["matched_required"],
                "missing_required": ats_result["missing_required"],
                "matched_preferred": ats_result["matched_preferred"],
                "missing_preferred": ats_result["missing_preferred"],
                "resume_data": resume_data,
            })
        except Exception as exc:
            logger.error("Failed to evaluate resume '%s': %s", display_name, exc, exc_info=True)
            evaluations.append({
                "candidate_name": Path(display_name).stem.title(),
                "filename": display_name,
                "file_path": path,
                "score": 0,
                "breakdown": {},
                "status": f"❌ Error: {str(exc)}",
                "recommendation": "Parsing Error",
                "contact": {},
                "matched_required": [],
                "missing_required": ["Error reading file"],
                "matched_preferred": [],
                "missing_preferred": [],
                "resume_data": {},
            })

    # 3. Sort candidates by ATS score descending
    evaluations.sort(
        key=lambda x: (
            x["score"],
            x.get("breakdown", {}).get("required_skills", {}).get("score", 0),
            x.get("breakdown", {}).get("experience", {}).get("score", 0),
        ),
        reverse=True,
    )

    # Assign ranks
    for rank_idx, cand in enumerate(evaluations, 1):
        cand["rank"] = rank_idx

    top_candidate = evaluations[0] if evaluations else None

    # 4. Generate comparative executive summary
    executive_summary = build_executive_summary(target_role, evaluations)

    # 5. Build full Markdown ranking report
    markdown_report = generate_batch_ranking_markdown(
        target_role=target_role,
        jd_data=jd_data,
        ranked_candidates=evaluations,
        executive_summary=executive_summary,
    )

    return {
        "target_role": target_role,
        "total_evaluated": total_candidates,
        "top_pick": top_candidate,
        "leaderboard": evaluations,
        "executive_summary": executive_summary,
        "report_markdown": markdown_report,
    }


def build_executive_summary(target_role: str, ranked: List[Dict[str, Any]]) -> str:
    """Produces a recruiter-friendly comparative summary between candidates."""
    if not ranked:
        return "No candidates evaluated."

    top = ranked[0]
    total = len(ranked)

    if total == 1:
        return f"Evaluated 1 candidate ({top['candidate_name']}) with an ATS fit score of {top['score']}/100."

    second = ranked[1]
    summary = f"Evaluated {total} candidates for the {target_role} role. "
    summary += f"🥇 **{top['candidate_name']}** ranked #1 with an ATS score of **{top['score']}/100**, "

    if top["score"] > second["score"]:
        diff = top["score"] - second["score"]
        summary += f"outperforming runner-up {second['candidate_name']} ({second['score']}/100) by +{diff} points. "
    else:
        summary += f"tied with {second['candidate_name']} on overall points but leading on core skills match. "

    if not top["missing_required"]:
        summary += f"{top['candidate_name']} matched 100% of mandatory requirements."
    else:
        summary += f"Key areas to probe during the interview: {', '.join(s.title() for s in top['missing_required'][:2])}."

    return summary


def generate_batch_ranking_markdown(
    target_role: str,
    jd_data: Dict[str, Any],
    ranked_candidates: List[Dict[str, Any]],
    executive_summary: str = "",
) -> str:
    """Generates a professional Markdown leaderboard report."""
    top = ranked_candidates[0] if ranked_candidates else None

    md = f"""# 🏆 Candidate Ranking & Best Resume Evaluation

- **Target Job Opening:** {target_role}
- **Total Candidates Evaluated:** {len(ranked_candidates)}
- **Top Recommended Candidate:** **{top['candidate_name'] if top else 'None'}** ({top['score'] if top else 0}/100)

---

## 📌 Executive Hiring Summary

{executive_summary}

---

## 🥇 #1 Best Match Recommendation: {top['candidate_name'] if top else 'N/A'}

"""
    if top:
        top_bd = top.get("breakdown", {})
        req_score = top_bd.get("required_skills", {}).get("score", 0)
        req_max = top_bd.get("required_skills", {}).get("max", 40)
        exp_years = top_bd.get("experience", {}).get("detected_years", 0)
        contact = top.get("contact", {})

        md += f"""- **Candidate Name:** **{top['candidate_name']}**
- **Original File:** `{top['filename']}`
- **Overall Match Score:** `{top['score']}/100` ({top['status']})
- **Hiring Recommendation:** **{top['recommendation']}**
- **Experience Detected:** ~{exp_years} years
- **Core Skills Score:** {req_score}/{req_max} pts ({len(top['matched_required'])} mandatory skills matched)
"""
        if contact.get("email"):
            md += f"- **Contact Email:** {contact['email']}\n"
        if contact.get("phone"):
            md += f"- **Contact Phone:** {contact['phone']}\n"

        if top['missing_required']:
            md += f"\n> **Interview Probing Question:** Candidate is missing *{', '.join(s.title() for s in top['missing_required'])}*. Ask about past exposure or adaptability to this stack.\n"
        else:
            md += "\n> **Standout Qualification:** Candidate satisfies 100% of all required competencies.\n"

    md += """
---

## 📊 Candidate Comparison Leaderboard

| Rank | Candidate Name | Original File | Score | Core Skills Match | Detected Exp | Recommendation |
| :---: | :--- | :--- | :---: | :---: | :---: | :--- |
"""
    for c in ranked_candidates:
        bd = c.get("breakdown", {})
        req_score = bd.get("required_skills", {}).get("score", 0)
        req_max = bd.get("required_skills", {}).get("max", 40)
        exp_yrs = bd.get("experience", {}).get("detected_years", 0)

        rank_badge = "🥇 1st" if c['rank'] == 1 else ("🥈 2nd" if c['rank'] == 2 else ("🥉 3rd" if c['rank'] == 3 else f"#{c['rank']}"))
        md += f"| **{rank_badge}** | **{c['candidate_name']}** | `{c['filename']}` | **{c['score']}/100** | {req_score}/{req_max} | ~{exp_yrs} yrs | {c['recommendation']} |\n"

    md += """
---

## 🔍 Detailed Candidate Profiles

"""
    for c in ranked_candidates:
        bd = c.get("breakdown", {})
        contact = c.get("contact", {})
        email_str = f" | Email: {contact['email']}" if contact.get("email") else ""

        md += f"""### Rank #{c['rank']}: {c['candidate_name']} ({c['score']}/100)
- **Document:** `{c['filename']}`{email_str}
- **Status:** {c['status']} — *{c['recommendation']}*
- **Matched Skills:** {', '.join(s.title() for s in (c['matched_required'] + c['matched_preferred'])[:8]) if (c['matched_required'] + c['matched_preferred']) else 'None'}
"""
        if c['missing_required']:
            md += f"- **Missing Mandatory Skills:** {', '.join(s.title() for s in c['missing_required'])}\n"
        if c['missing_preferred']:
            md += f"- **Missing Bonus Skills:** {', '.join(s.title() for s in c['missing_preferred'])}\n"
        md += "\n"

    md += """---
*Generated by AI Resume ATS Analyzer & Candidate Ranking Engine.*
"""
    return md
