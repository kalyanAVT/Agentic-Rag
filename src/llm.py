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

Bring-your-own-key: a visitor can supply their own key / base URL / model for a
single request (the UI's Settings panel). The pipeline scopes those with
`llm_context()`, and every getter below consults them before the env, so the
planner, agent, synthesis and write-back need no changes. SECURITY: a visitor's
key lives only in that request context and the client built from it -- never on
the Trace, in logs, or on disk.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

DEFAULT_MODEL = "gpt-4o-mini"

# Per-request timeout (seconds) and retry cap. Kept short so a slow or stuck
# provider (e.g. a stalled free-tier backend) degrades to the deterministic
# offline fallback quickly instead of hanging the whole pipeline. Override via
# LLM_TIMEOUT / LLM_MAX_RETRIES in .env.
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 1

# Placeholder keys that mean "no real key configured" -> offline fallback path.
_PLACEHOLDER_KEYS = {"", "sk-change-me"}


@dataclass(frozen=True)
class LLMSettings:
    """A visitor's own LLM config for one request (bring-your-own-key).

    Applied as a complete set: an empty base_url means the OpenAI default and an
    empty model means DEFAULT_MODEL -- the server's LLM_BASE_URL / LLM_MODEL are
    NOT mixed in, so a visitor's key is never sent to the server's provider.
    """

    api_key: str = field(repr=False)  # repr=False: never printed into logs
    base_url: str = ""
    model: str = ""


# The visitor settings for the request currently executing; None => use env.
# A ContextVar (not a global) so concurrent requests in FastAPI's threadpool
# stay isolated from each other.
_request_settings: ContextVar[LLMSettings | None] = ContextVar(
    "llm_request_settings", default=None
)


@contextmanager
def llm_context(settings: LLMSettings | None):
    """Scope a visitor's LLM settings to the current request (no-op for None).
    Resets on exit so a pooled worker thread never leaks one request's key."""
    if settings is None:
        yield
        return
    reset = _request_settings.set(settings)
    try:
        yield
    finally:
        _request_settings.reset(reset)


def using_visitor_llm() -> bool:
    """True while a visitor's own LLM settings are in effect."""
    return _request_settings.get() is not None


def get_api_key() -> str:
    """The LLM key: the visitor's for this request, else LLM_API_KEY, else
    OPENAI_API_KEY (back-compat)."""
    settings = _request_settings.get()
    if settings is not None:
        return settings.api_key.strip()
    return (os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY", "")).strip()


def llm_enabled() -> bool:
    """True when a real API key is set (not empty, not the sk-change-me placeholder)."""
    return get_api_key() not in _PLACEHOLDER_KEYS


def get_model() -> str:
    """Model id to use for all LLM calls."""
    settings = _request_settings.get()
    if settings is not None:
        return settings.model.strip() or DEFAULT_MODEL
    return os.getenv("LLM_MODEL", DEFAULT_MODEL)


def get_base_url() -> str:
    """OpenAI-compatible endpoint, or "" for the OpenAI default."""
    settings = _request_settings.get()
    if settings is not None:
        return settings.base_url.strip()
    return os.getenv("LLM_BASE_URL", "").strip()


def validate_base_url(url: str) -> str:
    """Check a VISITOR-supplied base URL before the server sends their key to it.

    The server makes the HTTP call, so an unchecked URL would let anyone point
    the hosted instance at internal addresses (SSRF -- e.g. cloud metadata at
    169.254.169.254). We require https and a host that resolves only to public
    addresses. Raises ValueError (-> HTTP 422) otherwise; returns the URL without
    a trailing slash.

    Accepted limitation: this checks DNS at validation time, so a host that
    re-resolves to a private address between the check and the call (DNS
    rebinding) is not caught. The server's own LLM_BASE_URL is trusted config
    and is never passed through here (so a local Ollama URL in .env still works).
    """
    raw = (url or "").strip().rstrip("/")
    parsed = urlparse(raw)
    if parsed.scheme != "https":
        raise ValueError("The LLM base URL must start with https://.")
    if parsed.username or parsed.password:
        raise ValueError("The LLM base URL must not contain credentials.")
    host = parsed.hostname
    if not host:
        raise ValueError("The LLM base URL has no host.")
    try:
        port = parsed.port or 443
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except (ValueError, socket.gaierror) as exc:
        raise ValueError(f"Could not resolve the LLM host '{host}'.") from exc

    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%", 1)[0])
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not ip.is_global or ip.is_multicast:
            raise ValueError(
                f"The LLM base URL must point to a public address "
                f"('{host}' resolves to a private or reserved one)."
            )
    return raw


def _get_float(name: str, default: float) -> float:
    """Read a float env var, falling back to default on unset/invalid values."""
    try:
        return float(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


def _get_int(name: str, default: int) -> int:
    """Read an int env var, falling back to default on unset/invalid values."""
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


def get_client() -> Any:
    """Construct an OpenAI-compatible client for the configured provider.

    Honors LLM_BASE_URL so the same SDK can target OpenAI, OpenRouter, xAI Grok,
    etc. A bounded timeout and retry cap ensure a slow or stuck provider surfaces
    as an exception the call sites catch, degrading to the offline fallback rather
    than blocking indefinitely. The openai package is imported lazily so importing
    this module never hard-requires it.
    """
    from openai import OpenAI

    kwargs: dict[str, Any] = {
        "api_key": get_api_key(),
        "timeout": _get_float("LLM_TIMEOUT", DEFAULT_TIMEOUT),
        "max_retries": _get_int("LLM_MAX_RETRIES", DEFAULT_MAX_RETRIES),
    }
    base_url = get_base_url()
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)
