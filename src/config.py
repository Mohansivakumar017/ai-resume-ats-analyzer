import os
from pathlib import Path
from dotenv import load_dotenv

# Base paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
SAMPLES_DIR = BASE_DIR / "samples"

# Load environment variables
load_dotenv(BASE_DIR / ".env")


class Config:
    """Application configuration and scoring parameters."""

    # API Credentials
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

    # Gemini AI Models
    PRIMARY_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
    FALLBACK_MODELS: list = [
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.6-flash",
        "gemini-3.8-flash",
    ]

    # ATS Scoring Weights (Total: 100 points)
    WEIGHT_REQUIRED_SKILLS: float = 40.0
    WEIGHT_PREFERRED_SKILLS: float = 15.0
    WEIGHT_EXPERIENCE: float = 15.0
    WEIGHT_EDUCATION: float = 10.0
    WEIGHT_STRUCTURE: float = 10.0
    WEIGHT_KEYWORDS: float = 10.0

    # Paths
    CURATED_COURSES_PATH: Path = DATA_DIR / "curated_courses.json"
    SAMPLE_RESUME_PATH: Path = SAMPLES_DIR / "sample_resume.pdf"
    SAMPLE_JD_PATH: Path = SAMPLES_DIR / "sample_jd.txt"

    # Telegram limits
    MAX_MESSAGE_LENGTH: int = 4000


config = Config()
