import os
import json
import logging
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
logger = logging.getLogger(__name__)

# List of models in order of priority. gemini-3.5-flash is fast and stable.
DEFAULT_MODELS = [
    os.getenv("GEMINI_MODEL", "gemini-3.5-flash"),
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.8-flash",
]


def get_client() -> genai.Client:
    """Initialize and return Google GenAI client."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set in environment or .env file.")
    return genai.Client(api_key=api_key)


def generate_json_content(prompt: str, candidate_models: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Calls Gemini API with JSON response enforcement and model fallback
    to handle transient 503 high-demand errors gracefully.
    """
    client = get_client()
    models = candidate_models or DEFAULT_MODELS

    last_error = None
    config = types.GenerateContentConfig(
        temperature=0.2,
        response_mime_type="application/json"
    )

    for model_name in models:
        try:
            logger.info("Calling Gemini model: %s", model_name)
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config
            )
            raw_text = (response.text or "").strip()
            if not raw_text:
                raise ValueError(f"Empty response from model {model_name}")

            # Strip markdown fences if present
            if raw_text.startswith("```json"):
                raw_text = raw_text[7:]
            elif raw_text.startswith("```"):
                raw_text = raw_text[3:]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3]

            data = json.loads(raw_text.strip())
            return data

        except Exception as exc:
            last_error = exc
            logger.warning("Model %s failed with: %s. Trying next model...", model_name, exc)
            continue

    raise RuntimeError(f"All Gemini models failed. Last error: {last_error}")
