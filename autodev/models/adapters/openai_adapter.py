"""OpenAI model adapter."""

from __future__ import annotations

import os


class OpenAIAdapter:
    """Adapter for OpenAI models (GPT-4 family)."""

    def __init__(self) -> None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "OPENAI_API_KEY environment variable is not set. "
                "Please set it to use the OpenAI adapter."
            )
        try:
            import openai  # noqa: F401

            self._client = openai.OpenAI(api_key=api_key)
        except ImportError as exc:
            raise ImportError("openai package is required: pip install openai") from exc

    def generate(self, prompt: str, context: str = "", model: str = "gpt-4.1") -> str:
        messages = []
        if context:
            messages.append({"role": "system", "content": context})
        messages.append({"role": "user", "content": prompt})

        response = self._client.chat.completions.create(
            model=model,
            messages=messages,
        )
        return response.choices[0].message.content or ""
