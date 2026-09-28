"""Regression test: the pipeline degrades gracefully when the LLM API fails.

A key that is present but invalid (or any transient API error: rate limit,
network) must NOT crash a run. Every LLM call site -- planner, agent
tool-calling, and synthesis -- has to fall back to the deterministic offline
path so `make demo` always produces a full trace. See CLAUDE.md ground rule 2
("Always keep a working demo path").
"""

from __future__ import annotations

from types import SimpleNamespace

from src.demo import run_pipeline


def _make_boom_client(*args, **kwargs):
    """Stand-in OpenAI() whose every completion call raises.

    Mirrors the real client's attribute shape (`.chat.completions.create` and
    `.beta.chat.completions.parse`) so the code under test reaches the actual
    API call before failing -- exactly what an invalid key does at runtime.
    """

    def boom(*_a, **_k):
        raise RuntimeError("simulated API failure")

    completions = SimpleNamespace(create=boom, parse=boom)
    chat = SimpleNamespace(completions=completions)
    return SimpleNamespace(chat=chat, beta=SimpleNamespace(chat=chat))


def test_pipeline_survives_llm_api_failure(monkeypatch) -> None:
    # Present-but-broken key forces the live path in planner/agent/synthesis...
    monkeypatch.setenv("OPENAI_API_KEY", "sk-invalid-for-test")
    # ...but every OpenAI call blows up, so all three must fall back offline.
    monkeypatch.setattr("openai.OpenAI", _make_boom_client)

    trace = run_pipeline("What changed in the dashboard work and is it on track?")

    # No exception propagated, and we still produced a usable, cited trace.
    assert trace.answer
    assert "fallback" in trace.answer.lower()  # proves the offline path was taken
    assert len(trace.plan) >= 2
    assert len(trace.evidence) >= 1
    assert len(trace.citations) >= 1
    # Tool calls themselves still succeeded -- only the LLM decision layer failed.
    assert all(tc.success for tc in trace.tool_calls)
