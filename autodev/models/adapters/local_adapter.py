"""Local model adapter — stub that returns placeholder text."""

from __future__ import annotations


class LocalAdapter:
    """Placeholder adapter for local / offline models."""

    def generate(self, prompt: str, context: str = "", model: str = "local") -> str:
        """Return a stub response (replace with real local model integration)."""
        prefix = f"[local:{model}] "
        if context:
            return f"{prefix}Responding to prompt based on provided context."
        return f"{prefix}Responding to prompt: {prompt[:80]}..."
