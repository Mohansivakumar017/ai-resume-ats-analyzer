#!/usr/bin/env python3
"""
CLI Evaluation tool for AI Resume ATS Analyzer.
Usage:
    python cli.py --resume samples/sample_resume.pdf --jd samples/sample_jd.txt
"""
import argparse
import sys
from pathlib import Path

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from src.config import config
from src.services import (
    parse_resume,
    parse_job_description,
    evaluate_ats_fit,
    generate_resume_improvements,
    recommend_learning_paths,
)


def run_cli(resume_path: Path, jd_path: Path):
    if not resume_path.is_file():
        print(f"Error: Resume file '{resume_path}' does not exist.")
        sys.exit(1)
    if not jd_path.is_file():
        print(f"Error: Job description file '{jd_path}' does not exist.")
        sys.exit(1)

    with open(jd_path, "r", encoding="utf-8") as f:
        jd_text = f.read()

    print("=" * 60)
    print("📊 AI RESUME ATS EVALUATION")
    print("=" * 60)
    print(f"📄 Resume: {resume_path.name}")
    print(f"📝 Job Description: {jd_path.name}")
    print("\n⏳ Processing with Gemini AI...")

    # 1. Parse Resume
    resume_text, resume_data = parse_resume(str(resume_path))

    # 2. Parse JD
    jd_data = parse_job_description(jd_text)

    # 3. Calculate ATS Score
    ats_result = evaluate_ats_fit(resume_data, jd_data, resume_text)

    # 4. Generate Improvements
    improvements = generate_resume_improvements(resume_data, jd_data, ats_result)

    # 5. Course Recommendations
    courses = recommend_learning_paths(
        missing_required=ats_result.get("missing_required", []),
        missing_preferred=ats_result.get("missing_preferred", []),
        job_title=jd_data.get("job_title", "Target Role"),
    )

    score = ats_result["overall_score"]
    bd = ats_result["breakdown"]

    print("\n" + "=" * 60)
    print(f"🎯 OVERALL MATCH SCORE: {score}/100")
    print(f"Target Role: {jd_data.get('job_title', 'Target Role')}")
    print("=" * 60)

    print("\n📋 SCORE BREAKDOWN:")
    print(f"• Required Skills: {bd['required_skills']['score']}/{bd['required_skills']['max']}")
    print(f"• Preferred Skills: {bd['preferred_skills']['score']}/{bd['preferred_skills']['max']}")
    print(f"• Experience: {bd['experience']['score']}/{bd['experience']['max']} (~{bd['experience']['detected_years']} years detected)")
    print(f"• Education: {bd['education']['score']}/{bd['education']['max']}")
    print(f"• Structure: {bd['structure']['score']}/{bd['structure']['max']}")
    print(f"• Keywords: {bd['keywords']['score']}/{bd['keywords']['max']}")

    print("\n🔍 SKILL GAP ANALYSIS:")
    if ats_result["missing_required"]:
        print("🔴 Missing Required Skills:")
        for s in ats_result["missing_required"]:
            print(f"  • {s.title()}")
    else:
        print("🔴 Missing Required Skills: None! (Full match)")

    if ats_result["missing_preferred"]:
        print("\n🟡 Missing Preferred Skills:")
        for s in ats_result["missing_preferred"]:
            print(f"  • {s.title()}")
    else:
        print("\n🟡 Missing Preferred Skills: None!")

    print("\n💡 ACTIONABLE RESUME IMPROVEMENTS:")
    for idx, item in enumerate(improvements.get("critical_improvements", [])[:3], 1):
        print(f"\n[{idx}] {item.get('section', 'General')}: {item.get('suggestion')}")
        print(f"    Example: {item.get('example_transformation')}")

    if courses:
        print("\n📚 RECOMMENDED LEARNING PATHS:")
        for c in courses[:4]:
            link = f" -> {c['url']}" if c.get("url") else ""
            print(f"• {c.get('course')} ({c.get('skill', '').title()}) [{c.get('platform')}]{link}")

    print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Evaluate resume against job description using AI ATS engine.")
    parser.add_argument(
        "--resume",
        type=Path,
        default=config.SAMPLE_RESUME_PATH,
        help="Path to resume PDF file (default: samples/sample_resume.pdf)"
    )
    parser.add_argument(
        "--jd",
        type=Path,
        default=config.SAMPLE_JD_PATH,
        help="Path to job description text file (default: samples/sample_jd.txt)"
    )
    args = parser.parse_args()
    run_cli(args.resume, args.jd)


if __name__ == "__main__":
    main()
