"""Anthropic (Claude) model adapter."""

from __future__ import annotations

import os


class AnthropicAdapter:
    """Adapter for Anthropic Claude models."""

    def __init__(self) -> None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "ANTHROPIC_API_KEY environment variable is not set. "
                "Please set it to use the Anthropic adapter."
            )
        try:
            import anthropic  # noqa: F401
            self._client = anthropic.Anthropic(api_key=api_key)
        except ImportError as exc:
            raise ImportError(
                "anthropic package is required: pip install anthropic"
            ) from exc

    def generate(self, prompt: str, context: str = "", model: str = "claude-sonnet-4-5") -> str:
        system = context if context else "You are a helpful software engineering assistant."
        message = self._client.messages.create(
            model=model,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text if message.content else ""
