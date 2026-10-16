"""
Tests for bring-your-own-key (the UI's Settings panel) and the privacy rules
that come with many visitors sharing one server.

Covers:
  * per-request LLM settings win over the server's env -- as a complete set --
    and are cleared when the request ends;
  * the base-URL check that stops visitors pointing the server at internal
    addresses (SSRF);
  * the API never echoes a key or token back, even in a validation error;
  * runs against a PRIVATE repo are never persisted, written to shared memory,
    or sent to Langfuse;
  * memory is scoped per repo (recall, dedup, write-back tagging, and upgrading
    a pre-existing DB).

No network: DNS lookups and GitHub calls are stubbed.
"""

from __future__ import annotations

import socket
import sqlite3

import pytest
from fastapi.testclient import TestClient

from src import llm as llm_mod
from src.llm import LLMSettings, llm_context, validate_base_url
from src.memory.store import MemoryStore
from src.tools import github_tools
from src.tracing.models import EvidenceItem, MemoryEntry, ToolCall, Trace


@pytest.fixture
def server_llm_env(monkeypatch):
    """A real-looking server config, so tests can prove the visitor's wins."""
    monkeypatch.setenv("LLM_API_KEY", "sk-SERVER")
    monkeypatch.setenv("LLM_BASE_URL", "https://server.example/v1")
    monkeypatch.setenv("LLM_MODEL", "server-model")


# --- per-request LLM settings ----------------------------------------------

def test_visitor_settings_override_env_then_reset(server_llm_env):
    visitor = LLMSettings(api_key="sk-VISITOR", base_url="https://api.x.ai/v1", model="grok-x")
    with llm_context(visitor):
        assert llm_mod.get_api_key() == "sk-VISITOR"
        assert llm_mod.get_base_url() == "https://api.x.ai/v1"
        assert llm_mod.get_model() == "grok-x"
        assert llm_mod.using_visitor_llm() is True
    # Back to the server's config once the request ends.
    assert llm_mod.get_api_key() == "sk-SERVER"
    assert llm_mod.get_base_url() == "https://server.example/v1"
    assert llm_mod.get_model() == "server-model"
    assert llm_mod.using_visitor_llm() is False


def test_visitor_settings_never_mix_with_server_config(server_llm_env):
    # Key only: base URL/model must NOT fall back to the server's -- that would
    # send the visitor's key to the server's provider.
    with llm_context(LLMSettings(api_key="sk-VISITOR")):
        assert llm_mod.get_base_url() == ""          # OpenAI default
        assert llm_mod.get_model() == llm_mod.DEFAULT_MODEL


def test_visitor_key_enables_llm_even_when_server_is_offline(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-change-me")
    assert llm_mod.llm_enabled() is False
    with llm_context(LLMSettings(api_key="sk-VISITOR")):
        assert llm_mod.llm_enabled() is True
    assert llm_mod.llm_enabled() is False


def test_llm_context_none_is_a_no_op(server_llm_env):
    with llm_context(None):
        assert llm_mod.get_api_key() == "sk-SERVER"


def test_llm_context_resets_on_exception(server_llm_env):
    with pytest.raises(RuntimeError):
        with llm_context(LLMSettings(api_key="sk-VISITOR")):
            raise RuntimeError("boom")
    assert llm_mod.get_api_key() == "sk-SERVER"


def test_get_client_uses_visitor_settings(monkeypatch, server_llm_env):
    import openai

    captured = {}
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: captured.update(kw) or object())
    with llm_context(LLMSettings(api_key="sk-VISITOR", base_url="https://api.x.ai/v1")):
        llm_mod.get_client()
    assert captured["api_key"] == "sk-VISITOR"
    assert captured["base_url"] == "https://api.x.ai/v1"


def test_llm_settings_repr_hides_key():
    assert "sk-VISITOR" not in repr(LLMSettings(api_key="sk-VISITOR", model="m"))


# --- base URL check (SSRF guard) -------------------------------------------

def _resolve_to(monkeypatch, *ips):
    def _fake(host, port, *args, **kwargs):
        return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))
                for ip in ips]
    monkeypatch.setattr(llm_mod.socket, "getaddrinfo", _fake)


def test_base_url_public_https_is_accepted(monkeypatch):
    _resolve_to(monkeypatch, "104.18.2.115")
    assert validate_base_url("https://openrouter.ai/api/v1/") == "https://openrouter.ai/api/v1"


@pytest.mark.parametrize(
    "url",
    ["http://openrouter.ai/api/v1", "ftp://x.example", "openrouter.ai/api/v1", "", "https://"],
)
def test_base_url_must_be_https_with_a_host(monkeypatch, url):
    _resolve_to(monkeypatch, "104.18.2.115")
    with pytest.raises(ValueError):
        validate_base_url(url)


def test_base_url_rejects_embedded_credentials(monkeypatch):
    _resolve_to(monkeypatch, "104.18.2.115")
    with pytest.raises(ValueError):
        validate_base_url("https://user:pass@openrouter.ai/api/v1")


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",          # loopback
        "10.0.0.5",           # private
        "192.168.1.10",       # private
        "172.16.0.1",         # private
        "169.254.169.254",    # cloud metadata (link-local)
        "0.0.0.0",
        "::1",                # IPv6 loopback
        "fd00::1",            # IPv6 unique-local
        "::ffff:127.0.0.1",   # IPv4-mapped loopback
    ],
)
def test_base_url_rejects_non_public_addresses(monkeypatch, ip):
    _resolve_to(monkeypatch, ip)
    with pytest.raises(ValueError):
        validate_base_url("https://sneaky.example/v1")


def test_base_url_rejected_if_any_resolved_address_is_private(monkeypatch):
    _resolve_to(monkeypatch, "104.18.2.115", "10.0.0.5")
    with pytest.raises(ValueError):
        validate_base_url("https://mixed.example/v1")


def test_base_url_unresolvable_host(monkeypatch):
    def _fail(*args, **kwargs):
        raise socket.gaierror("nope")
    monkeypatch.setattr(llm_mod.socket, "getaddrinfo", _fail)
    with pytest.raises(ValueError):
        validate_base_url("https://does-not-exist.example/v1")


# --- API: settings plumbing, secrets never echoed --------------------------

@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-change-me")
    monkeypatch.setenv("GITHUB_MCP_MODE", "none")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_change-me")
    monkeypatch.setenv("MEMORY_DB_PATH", ":memory:")
    monkeypatch.setenv("TRACE_DIR", str(tmp_path / "traces"))

    from src.api.main import app

    return TestClient(app)


def _capture_pipeline(monkeypatch):
    seen = {}

    def _fake(question, store, repo=None, github_token=None, llm=None):
        seen.update(repo=repo, github_token=github_token, llm=llm)
        return Trace(run_id="byok", question=question, answer="ok")

    monkeypatch.setattr("src.api.main.run_pipeline", _fake)
    return seen


def test_ask_forwards_llm_settings_without_echoing_secrets(client, monkeypatch):
    seen = _capture_pipeline(monkeypatch)
    resp = client.post(
        "/ask",
        json={
            "question": "q",
            "github_token": "ghp_SECRET",
            "llm_api_key": "sk-SECRET",
            "llm_base_url": "https://openrouter.ai/api/v1",
            "llm_model": "openrouter/free",
        },
    )
    assert resp.status_code == 200
    assert seen["llm"] == LLMSettings(
        api_key="sk-SECRET", base_url="https://openrouter.ai/api/v1", model="openrouter/free"
    )
    assert seen["github_token"] == "ghp_SECRET"
    assert "sk-SECRET" not in resp.text and "ghp_SECRET" not in resp.text


def test_ask_ignores_llm_url_and_model_without_a_key(client, monkeypatch):
    seen = _capture_pipeline(monkeypatch)
    resp = client.post(
        "/ask",
        json={"question": "q", "llm_base_url": "https://x.example/v1", "llm_model": "m",
              "llm_api_key": "   ", "github_token": ""},
    )
    assert resp.status_code == 200
    assert seen["llm"] is None              # -> the server's own config
    assert seen["github_token"] is None


def test_validation_error_does_not_echo_secrets(client):
    # Missing question -> 422. FastAPI would normally echo the whole body back.
    resp = client.post("/ask", json={"llm_api_key": "sk-SECRET", "github_token": "ghp_SECRET"})
    assert resp.status_code == 422
    assert "sk-SECRET" not in resp.text and "ghp_SECRET" not in resp.text


def test_ask_rejects_insecure_llm_base_url(client):
    # Real pipeline: the http:// check fails before any DNS or LLM call.
    resp = client.post(
        "/ask",
        json={"question": "q", "llm_api_key": "sk-x", "llm_base_url": "http://169.254.169.254/v1"},
    )
    assert resp.status_code == 422
    assert "https" in resp.json()["detail"]


# --- pipeline: settings scoping, private runs, memory tagging --------------

@pytest.fixture
def offline_env(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-change-me")
    trace_dir = tmp_path / "traces"
    monkeypatch.setenv("TRACE_DIR", str(trace_dir))
    return trace_dir


def _stub_live_repo(monkeypatch, private: bool):
    """No network: the repo check reports `private`, tools return one item."""
    monkeypatch.setattr("src.pipeline.preflight_repo", lambda repo, token: private)

    def _fake_call_tool(tool_name, args):
        ev = EvidenceItem(source="issue", id="issue-1", text="stub",
                          url="https://github.com/owner/name/issues/1")
        return [ev], ToolCall(tool_name=tool_name, args=args, result=[ev.model_dump()])

    monkeypatch.setattr(github_tools, "call_tool", _fake_call_tool)


def test_visitor_llm_settings_apply_only_inside_the_run(offline_env, monkeypatch):
    from src import pipeline

    seen = {}

    def _fake_execute(question, store, repo, private):
        seen.update(key=llm_mod.get_api_key(), model=llm_mod.get_model())
        return Trace(run_id="x", question=question)

    monkeypatch.setattr(pipeline, "_execute", _fake_execute)
    pipeline.run_pipeline("q", None, llm=LLMSettings(api_key="sk-VISITOR", model="m1"))
    assert seen == {"key": "sk-VISITOR", "model": "m1"}
    assert llm_mod.get_api_key() == "sk-change-me"     # cleared afterwards


def test_private_repo_run_is_never_persisted_or_remembered(offline_env, monkeypatch):
    _stub_live_repo(monkeypatch, private=True)
    calls = {"extract": 0, "emit": 0}
    monkeypatch.setattr(
        "src.pipeline.extract_memories",
        lambda *a, **k: calls.__setitem__("extract", calls["extract"] + 1) or [],
    )
    monkeypatch.setattr(
        "src.pipeline.emit_trace", lambda t: calls.__setitem__("emit", calls["emit"] + 1)
    )

    from src.pipeline import run_pipeline

    store = MemoryStore(":memory:")
    try:
        trace = run_pipeline("What issues are open?", store, repo="owner/secret",
                             github_token="ghp_SECRET")
    finally:
        store.close()

    assert trace.private is True
    assert not offline_env.exists() or not any(offline_env.iterdir())   # nothing saved
    assert calls == {"extract": 0, "emit": 0}                           # no write-back, no Langfuse


def test_public_repo_run_is_persisted_and_memory_tagged(offline_env, monkeypatch):
    _stub_live_repo(monkeypatch, private=False)
    monkeypatch.setattr(
        "src.pipeline.extract_memories",
        lambda q, a, e, run_id: [MemoryEntry(id="f1", text="Release 3.0 is blocked by issue 1.",
                                             topic_tags=["release"], source_run_id=run_id)],
    )

    from src.pipeline import run_pipeline

    store = MemoryStore(":memory:")
    try:
        trace = run_pipeline("What issues are open?", store, repo="owner/name",
                             github_token="ghp_SECRET")
        assert trace.private is False
        assert [e.repo for e in store.all("owner/name")] == ["owner/name"]
        assert store.all("") == []                       # not filed under the demo
    finally:
        store.close()

    assert any(offline_env.iterdir())                    # public run is saved
    assert "ghp_SECRET" not in trace.model_dump_json()


# --- memory scoped per repo --------------------------------------------------

def test_recall_only_returns_facts_about_the_same_repo():
    store = MemoryStore(":memory:")
    store.add(MemoryEntry(id="demo", text="PR 103 pagination fix is open.", topic_tags=["pagination"]))
    store.add(MemoryEntry(id="req", text="Requests pagination helper was deprecated.",
                          topic_tags=["pagination"], repo="psf/requests"))

    assert [e.id for e in store.retrieve("pagination status")] == ["demo"]
    assert [e.id for e in store.retrieve("pagination status", repo="psf/requests")] == ["req"]
    assert store.retrieve("pagination status", repo="other/repo") == []
    store.close()


def test_dedup_only_compares_facts_within_a_repo():
    store = MemoryStore(":memory:")
    fact = "The pagination fix is the top priority."
    assert store.add(MemoryEntry(id="a", text=fact, topic_tags=["pagination"])) is True
    # Same text about a different repo is a different fact.
    assert store.add(MemoryEntry(id="b", text=fact, topic_tags=["pagination"], repo="o/n")) is True
    # Same text, same repo -> duplicate.
    assert store.add(MemoryEntry(id="c", text=fact, topic_tags=["pagination"], repo="o/n")) is False
    store.close()


def test_existing_db_is_upgraded_and_old_facts_belong_to_the_demo(tmp_path):
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE memories (id TEXT PRIMARY KEY, text TEXT NOT NULL, "
        "topic_tags TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL, "
        "source_run_id TEXT NOT NULL DEFAULT '')"
    )
    conn.execute(
        "INSERT INTO memories VALUES ('old', 'Pagination fix must merge before Sept 20.', "
        "'[\"pagination\"]', '2026-09-15T00:00:00+00:00', 'seed')"
    )
    conn.commit()
    conn.close()

    store = MemoryStore(db)
    try:
        (entry,) = store.all()
        assert entry.repo == ""
        assert [e.id for e in store.retrieve("pagination fix")] == ["old"]
        assert store.retrieve("pagination fix", repo="psf/requests") == []
    finally:
        store.close()


# --- a failed visitor key is reported, not mistaken for "no key" ------------

def test_fallback_answer_says_when_the_llm_call_failed(monkeypatch):
    from src.synthesis.synthesizer import _fallback_synthesis

    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-change-me")
    assert "no LLM API key set" in _fallback_synthesis("q", [], [])
    with llm_context(LLMSettings(api_key="sk-wrong")):
        assert "LLM call failed" in _fallback_synthesis("q", [], [])
