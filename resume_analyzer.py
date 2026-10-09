import os
import json
from pathlib import Path
from typing import Tuple, Dict, Any
from pypdf import PdfReader
from ai_service import generate_json_content


def extract_resume(file_path: str = "resume.pdf") -> Tuple[str, Dict[str, Any]]:
    """
    Extracts text from a resume PDF and parses structured data using Gemini.
    Returns:
        (resume_text, resume_data)
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Resume file not found at: {file_path}")

    reader = PdfReader(str(path))
    resume_text = ""
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            resume_text += page_text + "\n"

    resume_text = resume_text.strip()
    if not resume_text:
        raise ValueError("Could not extract any text from the provided PDF resume.")

    prompt = f"""
Extract structured information from the resume below.
Return ONLY valid JSON.
Do not invent information.

JSON format:
{{
    "skills": [],
    "education": [],
    "experience": [],
    "projects": [],
    "certifications": []
}}

Resume:
{resume_text}
"""

    resume_data = generate_json_content(prompt)
    return resume_text, resume_data


if __name__ == "__main__":
    text, data = extract_resume()
    print("Resume Parsed Successfully:")
    print(json.dumps(data, indent=2))