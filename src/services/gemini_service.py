import json
import logging
from typing import Any, Dict, List, Optional
from google import genai
from google.genai import types

from src.config import config

logger = logging.getLogger(__name__)


class GeminiService:
    """Wrapper for Google Gemini API with fallback handling and JSON enforcement."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or config.GEMINI_API_KEY
        if not self.api_key:
            raise ValueError(
                "GEMINI_API_KEY is not set. Please add it to your .env file."
            )
        self.client = genai.Client(api_key=self.api_key)

    def generate_json(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        candidate_models: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Executes a Gemini call requesting JSON output.
        Automatically falls back through available models if demand spikes occur.
        """
        models_to_try = candidate_models or [config.PRIMARY_MODEL] + [
            m for m in config.FALLBACK_MODELS if m != config.PRIMARY_MODEL
        ]

        last_error = None
        gen_config = types.GenerateContentConfig(
            temperature=0.2,
            response_mime_type="application/json",
            system_instruction=system_instruction,
        )

        for model in models_to_try:
            try:
                logger.info("Executing Gemini prompt using model '%s'", model)
                response = self.client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=gen_config,
                )
                text = (response.text or "").strip()
                if not text:
                    raise ValueError(f"Received empty response from model {model}")

                # Clean markdown backticks if returned
                if text.startswith("```json"):
                    text = text[7:]
                elif text.startswith("```"):
                    text = text[3:]
                if text.endswith("```"):
                    text = text[:-3]

                return json.loads(text.strip())

            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Model '%s' failed (%s). Attempting next fallback model...",
                    model,
                    exc,
                )
                continue

        raise RuntimeError(
            f"All candidate Gemini models failed. Last error: {last_error}"
        )


# Singleton instance
gemini_service = GeminiService()
