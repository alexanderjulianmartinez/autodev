"""Google Gemini model adapter."""

from __future__ import annotations

import os


class GeminiAdapter:
    """Adapter for Google Gemini models."""

    def __init__(self) -> None:
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "GOOGLE_API_KEY environment variable is not set. "
                "Please set it to use the Gemini adapter."
            )
        try:
            import google.generativeai as genai  # noqa: F401
            genai.configure(api_key=api_key)
            self._genai = genai
        except ImportError as exc:
            raise ImportError(
                "google-generativeai package is required: pip install google-generativeai"
            ) from exc

    def generate(self, prompt: str, context: str = "", model: str = "gemini-pro") -> str:
        full_prompt = f"{context}\n\n{prompt}".strip() if context else prompt
        gen_model = self._genai.GenerativeModel(model)
        response = gen_model.generate_content(full_prompt)
        return response.text if response.text else ""
