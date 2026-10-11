import sys
import unittest
from pathlib import Path
import docx

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from src.services.resume_parser import parse_resume, extract_resume_text


class TestDocxParser(unittest.TestCase):
    """Verifies that .docx resumes are correctly extracted and parsed."""

    @classmethod
    def setUpClass(cls):
        cls.docx_path = BASE_DIR / "samples" / "sample_test_resume.docx"
        doc = docx.Document()
        doc.add_heading("Taylor Morgan", level=1)
        doc.add_paragraph("Email: taylor.morgan@example.com | Phone: +1 555-0144")
        doc.add_heading("Professional Summary", level=2)
        doc.add_paragraph("Full Stack Python and React engineer with experience in PostgreSQL and AWS cloud.")
        doc.add_heading("Skills", level=2)
        doc.add_paragraph("Python, FastAPI, Docker, PostgreSQL, React, Git, Linux")
        doc.add_heading("Experience", level=2)
        doc.add_paragraph("Software Engineer - TechCorp (2 years)")
        doc.add_paragraph("Engineered backend services and REST APIs using Python and FastAPI.")
        doc.save(str(cls.docx_path))

    @classmethod
    def tearDownClass(cls):
        if cls.docx_path.is_file():
            cls.docx_path.unlink()

    def test_extract_docx_text(self):
        text = extract_resume_text(str(self.docx_path))
        self.assertIn("Taylor Morgan", text)
        self.assertIn("FastAPI", text)
        self.assertIn("PostgreSQL", text)


if __name__ == "__main__":
    unittest.main()
