import sys
import unittest
from pathlib import Path

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from src.config import config
from src.services import (
    parse_resume,
    parse_job_description,
    evaluate_ats_fit,
    generate_resume_improvements,
    recommend_learning_paths,
)


class TestATSPipeline(unittest.TestCase):
    """End-to-end integration tests for the ATS analysis pipeline."""

    @classmethod
    def setUpClass(cls):
        cls.resume_path = config.SAMPLE_RESUME_PATH
        cls.jd_path = config.SAMPLE_JD_PATH

        if not cls.resume_path.is_file():
            raise FileNotFoundError(f"Missing sample resume at {cls.resume_path}")
        if not cls.jd_path.is_file():
            raise FileNotFoundError(f"Missing sample JD at {cls.jd_path}")

        with open(cls.jd_path, "r", encoding="utf-8") as f:
            cls.jd_text = f.read()

    def test_full_pipeline(self):
        print("\n" + "=" * 60)
        print("🧪 RUNNING END-TO-END ATS PIPELINE TEST")
        print("=" * 60)

        # 1. Parse Resume
        print("\n[1/5] Parsing PDF Resume...")
        resume_text, resume_data = parse_resume(str(self.resume_path))
        self.assertGreater(len(resume_text), 100)
        self.assertIn("skills", resume_data)
        print(f"  ✓ Extracted text length: {len(resume_text)} chars")
        print(f"  ✓ Detected skills: {len(resume_data['skills'])} skills")

        # 2. Parse Job Description
        print("\n[2/5] Parsing Job Description...")
        jd_data = parse_job_description(self.jd_text)
        self.assertIn("required_skills", jd_data)
        print(f"  ✓ Target Role: {jd_data.get('job_title', 'Backend Developer')}")
        print(f"  ✓ Required skills count: {len(jd_data.get('required_skills', []))}")

        # 3. Calculate ATS Score
        print("\n[3/5] Calculating ATS Score...")
        ats_result = evaluate_ats_fit(resume_data, jd_data, resume_text)
        score = ats_result["overall_score"]
        self.assertTrue(0 <= score <= 100)
        print(f"  ✓ Computed Overall ATS Score: {score}/100")
        print(f"  ✓ Required skills score: {ats_result['breakdown']['required_skills']['score']}")
        print(f"  ✓ Missing required: {ats_result['missing_required']}")
        print(f"  ✓ Missing preferred: {ats_result['missing_preferred']}")

        # 4. Generate Improvements
        print("\n[4/5] Generating Actionable Improvements...")
        improvements = generate_resume_improvements(resume_data, jd_data, ats_result)
        crit = improvements.get("critical_improvements", [])
        self.assertIsInstance(crit, list)
        print(f"  ✓ Generated {len(crit)} concrete improvement suggestions")

        # 5. Recommend Courses
        print("\n[5/5] Generating Learning Roadmaps...")
        courses = recommend_learning_paths(
            missing_required=ats_result.get("missing_required", []),
            missing_preferred=ats_result.get("missing_preferred", []),
            job_title=jd_data.get("job_title", "Target Role")
        )
        self.assertIsInstance(courses, list)
        print(f"  ✓ Recommended {len(courses)} targeted learning courses")

        print("\n" + "=" * 60)
        print("✅ ALL PIPELINE TESTS PASSED!")
        print("=" * 60)


if __name__ == "__main__":
    unittest.main()
