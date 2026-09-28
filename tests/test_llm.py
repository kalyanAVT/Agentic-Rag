"""Unit tests for the central LLM provider config (src/llm.py).

Verifies the provider-agnostic wiring the pipeline relies on: key precedence
(LLM_API_KEY over OPENAI_API_KEY), the placeholder -> offline-path logic in
llm_enabled(), model default/override, and LLM_BASE_URL passthrough (the one
knob that lets the same OpenAI SDK target OpenRouter / xAI Grok).
"""

from __future__ import annotations

from types import SimpleNamespace

import src.llm as llm


def test_get_api_key_prefers_llm_api_key(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("LLM_API_KEY", "sk-router")
    assert llm.get_api_key() == "sk-router"


def test_get_api_key_falls_back_to_openai(monkeypatch) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    assert llm.get_api_key() == "sk-openai"


def test_get_api_key_strips_whitespace(monkeypatch) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "  sk-openai  ")
    assert llm.get_api_key() == "sk-openai"


def test_llm_enabled_false_for_placeholder(monkeypatch) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-change-me")
    assert llm.llm_enabled() is False


def test_llm_enabled_false_when_empty(monkeypatch) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert llm.llm_enabled() is False


def test_llm_enabled_true_for_real_key(monkeypatch) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-1234")
    assert llm.llm_enabled() is True


def test_get_model_default_and_override(monkeypatch) -> None:
    monkeypatch.delenv("LLM_MODEL", raising=False)
    assert llm.get_model() == "gpt-4o-mini"
    monkeypatch.setenv("LLM_MODEL", "google/gemini-2.0-flash-exp:free")
    assert llm.get_model() == "google/gemini-2.0-flash-exp:free"


def test_get_client_passes_base_url(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_openai(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(**kwargs)

    monkeypatch.setattr("openai.OpenAI", fake_openai)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real")
    monkeypatch.setenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")

    llm.get_client()

    assert captured["api_key"] == "sk-real"
    assert captured["base_url"] == "https://openrouter.ai/api/v1"


def test_get_client_omits_base_url_when_unset(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_openai(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(**kwargs)

    monkeypatch.setattr("openai.OpenAI", fake_openai)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real")

    llm.get_client()

    assert "base_url" not in captured
