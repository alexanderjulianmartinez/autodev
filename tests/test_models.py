"""Tests for model components."""

import os

import pytest

from autodev.models.adapters.local_adapter import LocalAdapter
from autodev.models.router import ModelRouter


class TestLocalAdapter:
    def test_generate_returns_string(self):
        adapter = LocalAdapter()
        result = adapter.generate("What is 2+2?")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_generate_with_context(self):
        adapter = LocalAdapter()
        result = adapter.generate("Summarize this", context="Some context here")
        assert isinstance(result, str)

    def test_generate_model_param(self):
        adapter = LocalAdapter()
        result = adapter.generate("Hello", model="my-local-model")
        assert "my-local-model" in result


class TestOpenAIAdapter:
    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from autodev.models.adapters.openai_adapter import OpenAIAdapter
        with pytest.raises(EnvironmentError, match="OPENAI_API_KEY"):
            OpenAIAdapter()


class TestAnthropicAdapter:
    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        from autodev.models.adapters.anthropic_adapter import AnthropicAdapter
        with pytest.raises(EnvironmentError, match="ANTHROPIC_API_KEY"):
            AnthropicAdapter()


class TestGeminiAdapter:
    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        from autodev.models.adapters.gemini_adapter import GeminiAdapter
        with pytest.raises(EnvironmentError, match="GOOGLE_API_KEY"):
            GeminiAdapter()


class TestModelRouter:
    def test_routes_to_local_by_default(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        router = ModelRouter()
        result = router.generate("Hello", model_key="default")
        assert isinstance(result, str)
        assert "[local:" in result

    def test_routes_openai_key_to_openai_prefix(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        router = ModelRouter()
        provider = router._resolve_provider("gpt-4.1")
        assert provider == "openai"

    def test_routes_anthropic_key_to_anthropic_prefix(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        router = ModelRouter()
        provider = router._resolve_provider("claude-sonnet")
        assert provider == "anthropic"

    def test_unknown_model_key_falls_back_to_local(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        router = ModelRouter()
        result = router.generate("Hello", model_key="nonexistent_key")
        assert isinstance(result, str)
