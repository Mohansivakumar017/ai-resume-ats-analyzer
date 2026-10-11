import sys
import unittest
from pathlib import Path

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from src.config import config
from src.services.batch_ranker import rank_resumes


class TestBatchRanker(unittest.TestCase):
    """Integration test for batch candidate ranking and top pick selection."""

    def test_ranking_multiple_candidates(self):
        sample_files = [
            str(config.SAMPLES_DIR / "sample_candidate_alex.pdf"),
            str(config.SAMPLES_DIR / "sample_resume.pdf"),
            str(config.SAMPLES_DIR / "sample_candidate_jordan.pdf"),
        ]

        # Verify all sample files exist
        for f in sample_files:
            self.assertTrue(Path(f).is_file(), f"Sample resume not found: {f}")

        with open(config.SAMPLE_JD_PATH, "r", encoding="utf-8") as f:
            jd_text = f.read()

        ranking = rank_resumes(sample_files, jd_text)

        self.assertEqual(ranking["total_evaluated"], 3)
        self.assertIsNotNone(ranking["top_pick"])
        self.assertIn("report_markdown", ranking)

        leaderboard = ranking["leaderboard"]
        self.assertEqual(len(leaderboard), 3)

        # Check ranking order
        self.assertEqual(leaderboard[0]["rank"], 1)
        self.assertEqual(leaderboard[1]["rank"], 2)
        self.assertEqual(leaderboard[2]["rank"], 3)

        # Check top pick has highest score
        self.assertGreaterEqual(leaderboard[0]["score"], leaderboard[1]["score"])
        self.assertGreaterEqual(leaderboard[1]["score"], leaderboard[2]["score"])


if __name__ == "__main__":
    unittest.main()
