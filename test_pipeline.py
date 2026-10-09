import os
import json
from pathlib import Path

from resume_analyzer import extract_resume
from jd_analyzer import extract_jd
from ats_scorer import calculate_ats_score
from improvement_generator import generate_improvements
from course_recommender import recommend_courses


def run_pipeline():
    print("=" * 60)
    print("🚀 RUNNING END-TO-END RESUME ATS PIPELINE TEST")
    print("=" * 60)

    # 1. Check Sample Files
    resume_path = Path(__file__).parent / "resume.pdf"
    jd_path = Path(__file__).parent / "job_description.txt"

    if not resume_path.is_file():
        raise FileNotFoundError(f"Missing test resume at {resume_path}")
    if not jd_path.is_file():
        raise FileNotFoundError(f"Missing test job description at {jd_path}")

    with open(jd_path, "r", encoding="utf-8") as f:
        jd_text = f.read()

    # 2. Extract Resume
    print("\n[1/5] Extracting Resume...")
    resume_text, resume_data = extract_resume(str(resume_path))
    print(f"  ✓ Extracted text length: {len(resume_text)} characters")
    print(f"  ✓ Detected skills: {len(resume_data.get('skills', []))} skills found")

    # 3. Extract Job Description
    print("\n[2/5] Extracting Job Description Requirements...")
    jd_data = extract_jd(jd_text)
    print(f"  ✓ Target Title: {jd_data.get('job_title', 'Not specified')}")
    print(f"  ✓ Required skills: {jd_data.get('required_skills', [])}")
    print(f"  ✓ Preferred skills: {jd_data.get('preferred_skills', [])}")

    # 4. Calculate ATS Score
    print("\n[3/5] Calculating ATS Score...")
    ats_result = calculate_ats_score(resume_data, jd_data, resume_text)
    print(f"  ✓ Overall ATS Match Score: {ats_result['score']}/100")
    print(f"  ✓ Required Skills Score: {ats_result['required_skill_score']}/40")
    print(f"  ✓ Preferred Skills Score: {ats_result['preferred_skill_score']}/15")
    print(f"  ✓ Experience Score: {ats_result['experience_score']}/15")
    print(f"  ✓ Education Score: {ats_result['education_score']}/10")
    print(f"  ✓ Structure Score: {ats_result['structure_score']}/10")
    print(f"  ✓ Keyword Score: {ats_result['keyword_score']}/10")
    print(f"  ✓ Missing Required: {ats_result['missing_required']}")
    print(f"  ✓ Missing Preferred: {ats_result['missing_preferred']}")

    # 5. Generate Improvements
    print("\n[4/5] Generating Resume Improvements...")
    improvements = generate_improvements(resume_data, jd_data, ats_result)
    suggestions = improvements.get("improvements", [])
    print(f"  ✓ Generated {len(suggestions)} improvement suggestions")
    for idx, s in enumerate(suggestions[:3], 1):
        print(f"    {idx}. {s}")

    # 6. Recommend Courses
    print("\n[5/5] Recommending Courses...")
    courses = recommend_courses(
        missing_required=ats_result.get("missing_required", []),
        missing_preferred=ats_result.get("missing_preferred", [])
    )
    print(f"  ✓ Found {len(courses)} course recommendations")
    for c in courses[:3]:
        print(f"    • {c['course']} ({c['skill'].title()} - {c['priority']} priority)")

    print("\n" + "=" * 60)
    print("✅ ALL PIPELINE CHECKS COMPLETED SUCCESSFULLY!")
    print("=" * 60)


if __name__ == "__main__":
    run_pipeline()
