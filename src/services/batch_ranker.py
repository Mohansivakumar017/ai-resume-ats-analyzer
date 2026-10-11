import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.services.resume_parser import parse_resume
from src.services.jd_parser import parse_job_description
from src.services.ats_scorer import evaluate_ats_fit

logger = logging.getLogger(__name__)


def extract_candidate_name(resume_data: Dict[str, Any], resume_text: str, filename: str) -> str:
    """Extracts or infers candidate name from resume header or filename."""
    # Look at first 3 non-empty lines of text
    lines = [line.strip() for line in resume_text.split("\n") if line.strip()]
    for line in lines[:3]:
        # If line looks like a person's name (2-4 words, mostly alphabetic, not a heading)
        words = line.split()
        if 2 <= len(words) <= 4 and all(re.match(r"^[A-Za-z.\-']+$", w) for w in words):
            lower_line = line.lower()
            if not any(kw in lower_line for kw in ["resume", "curriculum", "vitae", "summary", "profile", "contact", "email"]):
                return line.title()

    # Fallback to cleaning filename
    stem = Path(filename).stem
    stem = re.sub(r"(sample|resume|cv|_|-)", " ", stem, flags=re.IGNORECASE)
    cleaned = stem.strip().title()
    return cleaned if cleaned else Path(filename).name


def rank_resumes(
    resume_paths: List[str],
    jd_text: str,
    jd_data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Evaluates multiple candidate resumes against a single job description,
    ranks them on an objective ATS leaderboard, and identifies the best candidate.
    """
    if not resume_paths:
        raise ValueError("At least one resume path must be provided for ranking.")

    # 1. Parse Job Description
    if not jd_data:
        jd_data = parse_job_description(jd_text)

    target_role = jd_data.get("job_title", "Target Role")
    total_candidates = len(resume_paths)
    evaluations = []

    logger.info("Ranking %d resumes for role '%s'", total_candidates, target_role)

    # 2. Evaluate each resume
    for path in resume_paths:
        try:
            resume_text, resume_data = parse_resume(path)
            ats_result = evaluate_ats_fit(resume_data, jd_data, resume_text)
            fname = Path(path).name
            cand_name = extract_candidate_name(resume_data, resume_text, fname)

            score = ats_result["overall_score"]
            bd = ats_result["breakdown"]

            if score >= 85:
                status = "🌟 Top Tier Match"
            elif score >= 70:
                status = "🟢 Strong Fit"
            elif score >= 50:
                status = "🟡 Moderate Fit"
            else:
                status = "🔴 Low Fit"

            evaluations.append({
                "candidate_name": cand_name,
                "filename": fname,
                "file_path": path,
                "score": score,
                "breakdown": bd,
                "matched_required": ats_result["matched_required"],
                "missing_required": ats_result["missing_required"],
                "matched_preferred": ats_result["matched_preferred"],
                "missing_preferred": ats_result["missing_preferred"],
                "status": status,
                "resume_data": resume_data,
            })
        except Exception as exc:
            logger.error("Failed to evaluate resume '%s': %s", path, exc, exc_info=True)
            evaluations.append({
                "candidate_name": Path(path).stem.title(),
                "filename": Path(path).name,
                "file_path": path,
                "score": 0,
                "breakdown": {},
                "matched_required": [],
                "missing_required": ["Error parsing resume"],
                "matched_preferred": [],
                "missing_preferred": [],
                "status": f"❌ Error: {str(exc)}",
                "resume_data": {},
            })

    # 3. Sort candidates (overall score desc, required skills desc, experience desc)
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

    # 4. Top Pick analysis
    top_candidate = evaluations[0] if evaluations else None

    # 5. Generate formatted markdown ranking report
    markdown_report = generate_batch_ranking_markdown(
        target_role=target_role,
        jd_data=jd_data,
        ranked_candidates=evaluations,
    )

    return {
        "target_role": target_role,
        "total_evaluated": total_candidates,
        "top_pick": top_candidate,
        "leaderboard": evaluations,
        "report_markdown": markdown_report,
    }


def generate_batch_ranking_markdown(
    target_role: str,
    jd_data: Dict[str, Any],
    ranked_candidates: List[Dict[str, Any]],
) -> str:
    """Generates a professional Markdown leaderboard report for multiple resumes."""
    top = ranked_candidates[0] if ranked_candidates else None

    md = f"""# 🏆 Candidate Ranking & Best Resume Evaluation

- **Target Job Opening:** {target_role}
- **Candidates Evaluated:** {len(ranked_candidates)}
- **Top Recommended Candidate:** **{top['candidate_name'] if top else 'None'}** ({top['score'] if top else 0}/100)

---

## 🥇 Best Match Recommendation: {top['candidate_name'] if top else 'N/A'}

"""
    if top:
        top_bd = top.get("breakdown", {})
        req_score = top_bd.get("required_skills", {}).get("score", 0)
        req_max = top_bd.get("required_skills", {}).get("max", 40)
        exp_years = top_bd.get("experience", {}).get("detected_years", 0)

        md += f"""**Overall Compatibility:** `{top['score']}/100` ({top['status']})  
**File:** `{top['filename']}`  
**Why this candidate is #1:**
- Matched **{len(top['matched_required'])}** core required skills ({req_score}/{req_max} pts).
- Relevant detected experience: **~{exp_years} years**.
"""
        if top['missing_required']:
            md += f"- **Key skill gap to explore:** {', '.join(s.title() for s in top['missing_required'])}\n"
        else:
            md += "- **Zero missing required skills:** Fully matches all mandatory qualifications 🎉\n"

    md += """
---

## 📊 Candidate Leaderboard

| Rank | Candidate | Overall Score | Required Skills | Detected Exp | Missing Mandatory Skills | Match Level |
| :---: | :--- | :---: | :---: | :---: | :--- | :--- |
"""
    for c in ranked_candidates:
        bd = c.get("breakdown", {})
        req_score = bd.get("required_skills", {}).get("score", 0)
        req_max = bd.get("required_skills", {}).get("max", 40)
        exp_yrs = bd.get("experience", {}).get("detected_years", 0)
        missing_str = ", ".join(s.title() for s in c["missing_required"][:2]) if c["missing_required"] else "None (Full Match)"

        rank_badge = "🥇 1st" if c['rank'] == 1 else ("🥈 2nd" if c['rank'] == 2 else ("🥉 3rd" if c['rank'] == 3 else f"{c['rank']}th"))
        md += f"| **{rank_badge}** | **{c['candidate_name']}**<br><small>`{c['filename']}`</small> | **{c['score']}/100** | {req_score}/{req_max} | ~{exp_yrs} yrs | {missing_str} | {c['status']} |\n"

    md += """
---

## 🔍 Candidate Breakdown & Details

"""
    for c in ranked_candidates:
        bd = c.get("breakdown", {})
        md += f"""### Rank #{c['rank']}: {c['candidate_name']} ({c['score']}/100)
- **Document:** `{c['filename']}`
- **Evaluation:** {c['status']}
- **Matched Competencies:** {', '.join(s.title() for s in (c['matched_required'] + c['matched_preferred'])[:6]) if (c['matched_required'] + c['matched_preferred']) else 'None'}
"""
        if c['missing_required']:
            md += f"- **Missing Mandatory Skills:** {', '.join(s.title() for s in c['missing_required'])}\n"
        if c['missing_preferred']:
            md += f"- **Missing Bonus Skills:** {', '.join(s.title() for s in c['missing_preferred'])}\n"
        md += "\n"

    md += """---
*Generated by AI Resume ATS Analyzer & Batch Ranking Engine.*
"""
    return md
