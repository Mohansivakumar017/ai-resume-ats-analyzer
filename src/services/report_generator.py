from datetime import datetime
from typing import Any, Dict, List


def format_progress_bar(score: float, max_score: float, width: int = 10) -> str:
    """Renders a visual ascii progress bar."""
    if max_score <= 0:
        return "░" * width
    ratio = max(0.0, min(1.0, score / max_score))
    filled = int(round(ratio * width))
    empty = width - filled
    return "█" * filled + "░" * empty


def generate_markdown_report(
    resume_name: str,
    jd_title: str,
    ats_result: Dict[str, Any],
    improvements: Dict[str, Any],
    courses: List[Dict[str, Any]],
) -> str:
    """
    Builds a beautifully structured Markdown document summarizing
    the complete ATS compatibility assessment.
    """
    score = ats_result["overall_score"]
    bd = ats_result["breakdown"]
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Score grade
    if score >= 85:
        grade = "Strong Match (Interview Ready)"
        badge = "🟢"
    elif score >= 70:
        grade = "Moderate Match (Minor Revisions Recommended)"
        badge = "🟡"
    else:
        grade = "Low Match (Needs Significant Tailoring)"
        badge = "🔴"

    md = f"""# 📊 AI Resume ATS Compatibility Report

- **Target Role:** {jd_title}
- **Resume File:** {resume_name}
- **Evaluation Date:** {now_str}
- **Overall Match Rating:** **{score}/100** ({grade}) {badge}

---

## 📈 Executive Summary

| Category | Score | Max Points | Progress | Status |
| :--- | :---: | :---: | :---: | :--- |
| **Required Skills** | {bd['required_skills']['score']} | {bd['required_skills']['max']} | `{format_progress_bar(bd['required_skills']['score'], bd['required_skills']['max'])}` | {'✅ Optimal' if bd['required_skills']['score'] >= 30 else '⚠️ Needs Attention'} |
| **Preferred Skills** | {bd['preferred_skills']['score']} | {bd['preferred_skills']['max']} | `{format_progress_bar(bd['preferred_skills']['score'], bd['preferred_skills']['max'])}` | {'✅ Strong' if bd['preferred_skills']['score'] >= 10 else 'ℹ️ Good to have'} |
| **Experience Tenure** | {bd['experience']['score']} | {bd['experience']['max']} | `{format_progress_bar(bd['experience']['score'], bd['experience']['max'])}` | Detected ~{bd['experience']['detected_years']} yrs |
| **Education Fit** | {bd['education']['score']} | {bd['education']['max']} | `{format_progress_bar(bd['education']['score'], bd['education']['max'])}` | Degree / Major Matched |
| **Structure & Layout** | {bd['structure']['score']} | {bd['structure']['max']} | `{format_progress_bar(bd['structure']['score'], bd['structure']['max'])}` | Standard Sections |
| **Keyword Coverage** | {bd['keywords']['score']} | {bd['keywords']['max']} | `{format_progress_bar(bd['keywords']['score'], bd['keywords']['max'])}` | Domain Vocabulary |
| **TOTAL ATS SCORE** | **{score}** | **100** | `{format_progress_bar(score, 100, 15)}` | **{grade}** |

---

## 🔍 Skill Gap Analysis

### 🔴 Mandatory Skills
"""
    if ats_result["missing_required"]:
        for s in ats_result["missing_required"]:
            md += f"- ❌ **{s.title()}** *(Mandatory requirement missing)*\n"
    else:
        md += "- ✅ **Full Coverage:** You meet or exceed all required skills for this role!\n"

    md += "\n### 🟡 Preferred & Bonus Qualifications\n"
    if ats_result["missing_preferred"]:
        for s in ats_result["missing_preferred"]:
            md += f"- ⚠️ **{s.title()}** *(Preferred qualification)*\n"
    else:
        md += "- ✅ **Bonus Coverage:** You meet all preferred qualifications!\n"

    # Matched Skills
    md += "\n### 🟢 Matched Core Competencies\n"
    all_matched = sorted(set(ats_result.get("matched_required", []) + ats_result.get("matched_preferred", [])))
    if all_matched:
        for s in all_matched:
            md += f"- ✓ `{s.title()}`\n"
    else:
        md += "- *No exact keyword matches found.*\n"

    # Improvements
    md += "\n---\n\n## 💡 Actionable Resume Rewrites & Recommendations\n\n"
    crit = improvements.get("critical_improvements", [])
    if crit:
        for idx, item in enumerate(crit, 1):
            md += f"### {idx}. {item.get('section', 'General Improvement')}\n"
            md += f"**Suggestion:** {item.get('suggestion')}\n\n"
            if item.get("example_transformation"):
                md += f"> **Example Transformation:**\n> {item.get('example_transformation')}\n\n"
    else:
        md += "- Resume phrasing is clear and impactful.\n\n"

    # Keyword strategy
    strat = improvements.get("ats_keyword_strategy", [])
    if strat:
        md += "### 🎯 ATS Keyword Strategy\n"
        for tip in strat:
            md += f"- {tip}\n"
        md += "\n"

    # Courses
    md += "---\n\n## 📚 Recommended Learning Paths & Certifications\n\n"
    if courses:
        for c in courses:
            url_part = f"([Course Link]({c['url']}))" if c.get("url") else ""
            md += f"- **{c.get('course')}** — *{c.get('skill', '').title()}*\n"
            md += f"  - **Platform:** {c.get('platform')} {url_part}\n"
            md += f"  - **Priority:** `{c.get('priority', 'MEDIUM')}` | **Level:** {c.get('level', 'All Levels')}\n"
            if c.get("reason"):
                md += f"  - **Why:** {c.get('reason')}\n"
            md += "\n"
    else:
        md += "- No critical skill gaps identified requiring supplemental coursework.\n\n"

    md += """---

*Generated automatically by AI Resume ATS Analyzer Engine.*
"""
    return md
