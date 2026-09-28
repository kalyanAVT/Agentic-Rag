"""
Central LLM client + model configuration.

The pipeline talks to its LLM through the OpenAI SDK, which speaks to any
OpenAI-compatible provider -- so switching providers is pure configuration, no
code change. Set these in `.env`:

    LLM_API_KEY    API key for the provider. Falls back to OPENAI_API_KEY.
    LLM_BASE_URL   OpenAI-compatible endpoint. Leave unset for OpenAI. Examples:
                     OpenRouter  https://openrouter.ai/api/v1
                     xAI Grok    https://api.x.ai/v1
    LLM_MODEL      Model id (default: gpt-4o-mini). Examples:
                     OpenRouter  google/gemini-2.0-flash-exp:free
                     xAI Grok    grok-2-latest

`llm_enabled()` is the single source of truth for whether to take the live LLM
path: True only when a real key is configured (not empty, not the placeholder).
Every LLM call site gates on it and otherwise runs the deterministic offline
fallback, so `make demo` always works (see docs/ARCHITECTURE.md).
"""

from __future__ import annotations

import os
from typing import Any

DEFAULT_MODEL = "gpt-4o-mini"

# Placeholder keys that mean "no real key configured" -> offline fallback path.
_PLACEHOLDER_KEYS = {"", "sk-change-me"}


def get_api_key() -> str:
    """The configured LLM key: LLM_API_KEY wins, else OPENAI_API_KEY (back-compat)."""
    return (os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY", "")).strip()


def llm_enabled() -> bool:
    """True when a real API key is set (not empty, not the sk-change-me placeholder)."""
    return get_api_key() not in _PLACEHOLDER_KEYS


def get_model() -> str:
    """Model id to use for all LLM calls."""
    return os.getenv("LLM_MODEL", DEFAULT_MODEL)


def get_client() -> Any:
    """Construct an OpenAI-compatible client for the configured provider.

    Honors LLM_BASE_URL so the same SDK can target OpenAI, OpenRouter, xAI Grok,
    etc. The openai package is imported lazily so importing this module never
    hard-requires it.
    """
    from openai import OpenAI

    kwargs: dict[str, Any] = {"api_key": get_api_key()}
    base_url = os.getenv("LLM_BASE_URL", "").strip()
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)
