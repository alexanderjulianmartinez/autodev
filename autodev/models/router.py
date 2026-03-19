"""ModelRouter: routes generation requests to the appropriate adapter."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Default model → provider mapping used when no config file is present.
_DEFAULT_MODEL_CONFIG: dict[str, str] = {
    "planner": "claude-sonnet",
    "coder": "gpt-4.1",
    "reviewer": "claude-opus",
    "debugger": "gpt-4.1",
    "default": "gpt-4.1",
}

_OPENAI_PREFIXES = ("gpt-",)
_ANTHROPIC_PREFIXES = ("claude-",)
_GEMINI_PREFIXES = ("gemini-",)


class ModelRouter:
    """Routes model.generate() calls to the correct provider adapter."""

    def __init__(self, config_path: str | None = None) -> None:
        self._config = self._load_config(config_path)
        self._adapters: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def generate(self, prompt: str, context: str = "", model_key: str = "default") -> str:
        """Generate a response using the adapter mapped to *model_key*."""
        model_name = self._config.get(model_key, self._config.get("default", "local"))
        adapter = self._get_adapter(model_name)
        return adapter.generate(prompt, context=context, model=model_name)

    # ------------------------------------------------------------------
    # Adapter resolution
    # ------------------------------------------------------------------

    def _get_adapter(self, model_name: str) -> Any:
        provider = self._resolve_provider(model_name)
        if provider not in self._adapters:
            self._adapters[provider] = self._build_adapter(provider)
        return self._adapters[provider]

    def _resolve_provider(self, model_name: str) -> str:
        lower = model_name.lower()
        if any(lower.startswith(p) for p in _OPENAI_PREFIXES):
            if os.environ.get("OPENAI_API_KEY"):
                return "openai"
        if any(lower.startswith(p) for p in _ANTHROPIC_PREFIXES):
            if os.environ.get("ANTHROPIC_API_KEY"):
                return "anthropic"
        if any(lower.startswith(p) for p in _GEMINI_PREFIXES):
            if os.environ.get("GOOGLE_API_KEY"):
                return "gemini"
        return "local"

    def _build_adapter(self, provider: str) -> Any:
        if provider == "openai":
            from autodev.models.adapters.openai_adapter import OpenAIAdapter

            return OpenAIAdapter()
        if provider == "anthropic":
            from autodev.models.adapters.anthropic_adapter import AnthropicAdapter

            return AnthropicAdapter()
        if provider == "gemini":
            from autodev.models.adapters.gemini_adapter import GeminiAdapter

            return GeminiAdapter()
        from autodev.models.adapters.local_adapter import LocalAdapter

        return LocalAdapter()

    # ------------------------------------------------------------------
    # Config loading
    # ------------------------------------------------------------------

    def _load_config(self, config_path: str | None) -> dict[str, str]:
        paths_to_try: list[Path] = []
        if config_path:
            paths_to_try.append(Path(config_path))
        paths_to_try.append(Path.home() / ".autodev" / "models.yaml")
        paths_to_try.append(Path(__file__).parent.parent.parent / "configs" / "models.yaml")

        for path in paths_to_try:
            if path.exists():
                try:
                    data = yaml.safe_load(path.read_text())
                    if isinstance(data, dict) and "models" in data:
                        return {str(k): str(v) for k, v in data["models"].items()}
                except Exception as exc:
                    logger.debug("Failed to load model config from %s: %s", path, exc)

        return dict(_DEFAULT_MODEL_CONFIG)
