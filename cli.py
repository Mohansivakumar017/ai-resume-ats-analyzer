#!/usr/bin/env python3
"""
CLI Evaluation tool for AI Resume ATS Analyzer.
Supports:
  1. Single Resume Evaluation & Improvement Report
     python cli.py --resume samples/sample_resume.pdf --jd samples/sample_jd.txt
  2. Multi-Resume Ranking & Best Candidate Picker
     python cli.py --rank --resumes samples/*.pdf --jd samples/sample_jd.txt
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
    generate_markdown_report,
    rank_resumes,
)


def run_single_cli(resume_path: Path, jd_path: Path, export_path: Path = None):
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

    # Export to markdown if requested
    if export_path:
        md_content = generate_markdown_report(
            resume_name=resume_path.name,
            jd_title=jd_data.get("job_title", "Target Role"),
            ats_result=ats_result,
            improvements=improvements,
            courses=courses,
        )
        with open(export_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        print(f"\n✅ Full ATS Report successfully exported to: {export_path}")

    print("\n" + "=" * 60)


def run_ranking_cli(resume_paths: list, jd_path: Path, export_path: Path = None):
    if not jd_path.is_file():
        print(f"Error: Job description file '{jd_path}' does not exist.")
        sys.exit(1)

    valid_paths = [str(p) for p in resume_paths if Path(p).is_file() and str(p).lower().endswith(".pdf")]
    if len(valid_paths) < 1:
        print("Error: No valid PDF resumes provided for ranking.")
        sys.exit(1)

    with open(jd_path, "r", encoding="utf-8") as f:
        jd_text = f.read()

    print("=" * 60)
    print("🏆 BATCH RESUME RANKING & BEST CANDIDATE EVALUATION")
    print("=" * 60)
    print(f"Evaluating {len(valid_paths)} resumes against: {jd_path.name}")
    print("\n⏳ Processing candidates with Gemini AI...")

    ranking_result = rank_resumes(valid_paths, jd_text)
    leaderboard = ranking_result["leaderboard"]
    top_pick = ranking_result["top_pick"]
    role = ranking_result["target_role"]

    print("\n" + "=" * 60)
    print(f"🥇 BEST RESUME MATCH: {top_pick['candidate_name'].upper()} ({top_pick['score']}/100)")
    print(f"Target Role: {role}")
    print(f"File: {top_pick['filename']}")
    print(f"Status: {top_pick['status']}")
    print("=" * 60)

    print("\n📊 CANDIDATE LEADERBOARD:")
    print(f"{'Rank':<6} | {'Score':<6} | {'Candidate Name':<25} | {'Filename':<30} | {'Status'}")
    print("-" * 85)
    for c in leaderboard:
        rank_str = f"#{c['rank']}"
        score_str = f"{c['score']}/100"
        print(f"{rank_str:<6} | {score_str:<6} | {c['candidate_name'][:25]:<25} | {c['filename'][:30]:<30} | {c['status']}")

    if export_path:
        with open(export_path, "w", encoding="utf-8") as f:
            f.write(ranking_result["report_markdown"])
        print(f"\n✅ Candidate Ranking Report exported to: {export_path}")

    print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(description="AI Resume ATS Analyzer & Batch Candidate Ranker.")
    parser.add_argument(
        "--resume",
        type=Path,
        default=config.SAMPLE_RESUME_PATH,
        help="Path to single resume PDF file (default: samples/sample_resume.pdf)"
    )
    parser.add_argument(
        "--resumes",
        nargs="+",
        help="List of multiple resume PDF files to rank"
    )
    parser.add_argument(
        "--resume-dir",
        type=Path,
        help="Directory containing multiple resume PDFs to rank"
    )
    parser.add_argument(
        "--rank",
        action="store_true",
        help="Enable batch candidate ranking mode"
    )
    parser.add_argument(
        "--jd",
        type=Path,
        default=config.SAMPLE_JD_PATH,
        help="Path to job description text file (default: samples/sample_jd.txt)"
    )
    parser.add_argument(
        "--export",
        type=Path,
        default=None,
        help="Path to export Markdown report (e.g., --export report.md)"
    )
    args = parser.parse_args()

    # Determine mode
    if args.rank or args.resumes or args.resume_dir:
        paths = []
        if args.resumes:
            paths.extend(args.resumes)
        if args.resume_dir and args.resume_dir.is_dir():
            paths.extend(list(args.resume_dir.glob("*.pdf")))
        if not paths:
            # Fallback to all samples
            paths = list(config.SAMPLES_DIR.glob("*.pdf"))
        run_ranking_cli(paths, args.jd, args.export)
    else:
        run_single_cli(args.resume, args.jd, args.export)


if __name__ == "__main__":
    main()
