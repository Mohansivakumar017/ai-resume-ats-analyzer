import logging
from pathlib import Path
from typing import Any, Dict, Tuple
from pypdf import PdfReader

from src.services.gemini_service import gemini_service

logger = logging.getLogger(__name__)


def extract_pdf_text(pdf_path: str) -> str:
    """Extracts raw text from a PDF file."""
    path = Path(pdf_path)
    if not path.is_file():
        raise FileNotFoundError(f"PDF file not found at: {pdf_path}")

    reader = PdfReader(str(path))
    extracted = []
    for i, page in enumerate(reader.pages):
        page_text = page.extract_text()
        if page_text:
            extracted.append(page_text.strip())

    full_text = "\n\n".join(extracted).strip()
    if not full_text:
        raise ValueError(
            "Could not extract readable text from PDF. Ensure the PDF is not an image scan."
        )
    return full_text


def parse_resume(pdf_path: str) -> Tuple[str, Dict[str, Any]]:
    """
    Parses a candidate's resume from a PDF file and returns:
    (raw_text, structured_data_dict)
    """
    raw_text = extract_pdf_text(pdf_path)

    prompt = f"""
You are an expert ATS (Applicant Tracking System) parser.
Extract structured information from the following resume text.

Return ONLY a valid JSON object matching this schema:
{{
    "skills": ["string"],
    "experience": [
        {{
            "title": "string",
            "organization": "string",
            "years": 0.0,
            "technologies": ["string"],
            "highlights": ["string"]
        }}
    ],
    "education": [
        {{
            "degree": "string",
            "field": "string",
            "institution": "string"
        }}
    ],
    "projects": [
        {{
            "name": "string",
            "technologies": ["string"],
            "description": "string"
        }}
    ],
    "certifications": ["string"]
}}

Resume Text:
{raw_text}
"""

    structured_data = gemini_service.generate_json(
        prompt=prompt,
        system_instruction="You are an unbiased, highly accurate ATS resume parser. Never fabricate missing details."
    )

    return raw_text, structured_data
