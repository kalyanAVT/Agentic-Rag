"""
Tests for the per-request live-GitHub feature (completes Phase 3): point a
single run at ANY github.com repo -- public, or private with a visitor-supplied
token -- from the API/UI, while the offline seed path is preserved when no repo
is given.

No network required: the only place that would call GitHub (``preflight_repo``)
is exercised with a stubbed PyGithub client, and the API's error->HTTP mapping is
tested by stubbing ``run_pipeline``. The SECURITY invariant under test -- a
supplied token must never appear in an error message, the Trace, or any HTTP
response -- is asserted directly.
"""

from __future__ import annotations

import github as _pygithub
import pytest
from fastapi.testclient import TestClient

from src import agent as agent_mod
from src.tools import github_tools, mock_tools
from src.tools.context import current_repo, current_token, github_context
from src.tools.repo import RepoAccessError, normalize_repo
from src.tracing.models import EvidenceItem, ToolCall, Trace


# --- repo reference parsing ------------------------------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("fastapi/fastapi", "fastapi/fastapi"),
        ("https://github.com/psf/requests", "psf/requests"),
        ("http://github.com/psf/requests", "psf/requests"),
        ("https://www.github.com/psf/requests", "psf/requests"),
        ("github.com/psf/requests", "psf/requests"),
        ("https://github.com/psf/requests/", "psf/requests"),
        ("https://github.com/psf/requests.git", "psf/requests"),
        ("https://github.com/a/b?tab=issues#readme", "a/b"),
        ("  owner/name  ", "owner/name"),
    ],
)
def test_normalize_repo_accepts_valid_forms(raw, expected):
    assert normalize_repo(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "not a repo",
        "only-owner",
        "a/b/c",
        "https://gitlab.com/x/y",          # non-github host rejected
        "https://example.com/a/b",
        "git@github.com:psf/requests.git",  # ssh form unsupported
    ],
)
def test_normalize_repo_rejects_bad_input(raw):
    with pytest.raises(ValueError):
        normalize_repo(raw)


# --- per-request context ---------------------------------------------------

def test_github_context_sets_and_resets():
    assert current_repo() is None and current_token() is None
    with github_context("owner/name", "ghp_x"):
        assert current_repo() == "owner/name"
        assert current_token() == "ghp_x"
    assert current_repo() is None and current_token() is None


def test_github_context_resets_on_exception():
    with pytest.raises(RuntimeError):
        with github_context("owner/name", None):
            raise RuntimeError("boom")
    # Context must be cleared even when the run raised, so a pooled worker
    # thread never leaks one request's repo/token into the next.
    assert current_repo() is None and current_token() is None


# --- live/offline routing --------------------------------------------------

def test_active_registry_switches_on_repo_context():
    assert github_tools._active_registry() is github_tools.TOOL_REGISTRY
    with github_context("owner/name", None):
        assert github_tools._active_registry() is github_tools.REST_TOOLS
    assert github_tools._active_registry() is github_tools.TOOL_REGISTRY


def test_agent_prefers_live_tools_when_repo_set(monkeypatch):
    # Even with an EMPTY env registry (the offline/no-key case), a per-request
    # repo must route to the live tools -- mock data for a real repo is wrong.
    monkeypatch.setattr(github_tools, "TOOL_REGISTRY", {})
    assert agent_mod._get_active_tools() is mock_tools.call_tool
    with github_context("owner/name", None):
        assert agent_mod._get_active_tools() is github_tools.call_tool


# --- preflight error mapping (stubbed PyGithub, no network) ----------------

class _FakeGithub:
    """Stand-in for PyGithub's Github client: get_repo optionally raises."""

    def __init__(self, exc=None):
        self._exc = exc
        self.closed = False

    def get_repo(self, name):
        if self._exc is not None:
            raise self._exc
        return object()

    def close(self):
        self.closed = True


def test_preflight_404_is_private_or_missing_and_hides_token(monkeypatch):
    created = {}

    def _factory(*args, **kwargs):
        created["gh"] = _FakeGithub(_pygithub.GithubException(status=404, data={"message": "Not Found"}))
        return created["gh"]

    monkeypatch.setattr(_pygithub, "Github", _factory)

    with pytest.raises(RepoAccessError) as excinfo:
        github_tools.preflight_repo("owner/secret", token="ghp_SUPERSECRET")

    msg = str(excinfo.value)
    assert "ghp_SUPERSECRET" not in msg       # token never leaked into the message
    assert "token" in msg.lower()             # actionable hint for the user
    assert created["gh"].closed is True       # client always closed


def test_preflight_redacts_token_in_other_errors(monkeypatch):
    # If a library ever echoes the token (e.g. in a URL/body), _redact scrubs it.
    exc = _pygithub.GithubException(status=500, data="upstream failure for ghp_SUPERSECRET")
    monkeypatch.setattr(_pygithub, "Github", lambda *a, **k: _FakeGithub(exc))

    with pytest.raises(RepoAccessError) as excinfo:
        github_tools.preflight_repo("owner/name", token="ghp_SUPERSECRET")

    msg = str(excinfo.value)
    assert "ghp_SUPERSECRET" not in msg
    assert "***" in msg


def test_preflight_ok_for_readable_repo(monkeypatch):
    gh = _FakeGithub(None)
    monkeypatch.setattr(_pygithub, "Github", lambda *a, **k: gh)
    github_tools.preflight_repo("octocat/Hello-World", token=None)  # must not raise
    assert gh.closed is True


# --- pipeline: repo on Trace, token never persisted ------------------------

def test_pipeline_records_repo_and_never_persists_token(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-change-me")   # force offline LLM
    monkeypatch.setenv("TRACE_DIR", str(tmp_path / "traces"))

    # No network: skip the real preflight and stub the live tool call.
    monkeypatch.setattr("src.pipeline.preflight_repo", lambda repo, token: None)

    def _fake_call_tool(tool_name, args):
        ev = EvidenceItem(
            source="issue", id="issue-1", text="stub evidence",
            url="https://github.com/owner/name/issues/1",
        )
        tc = ToolCall(tool_name=tool_name, args=args, result=[ev.model_dump()],
                      latency_ms=1, success=True)
        return [ev], tc

    monkeypatch.setattr(github_tools, "call_tool", _fake_call_tool)

    from src.memory.store import MemoryStore
    from src.pipeline import run_pipeline

    store = MemoryStore(":memory:")
    try:
        trace = run_pipeline(
            "What issues are open?", store,
            repo="https://github.com/owner/name", token="ghp_SUPERSECRET",
        )
    finally:
        store.close()

    assert trace.repo == "owner/name"                 # normalized and recorded
    assert "ghp_SUPERSECRET" not in trace.model_dump_json()   # token off the Trace


# --- API: repo/token plumbing + error mapping ------------------------------

@pytest.fixture
def client(monkeypatch, tmp_path):
    # Mirror tests/test_api_runs.py: force offline, mock data, isolated storage.
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-change-me")
    monkeypatch.setenv("GITHUB_MCP_MODE", "none")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_change-me")
    monkeypatch.setenv("MEMORY_DB_PATH", ":memory:")
    monkeypatch.setenv("TRACE_DIR", str(tmp_path / "traces"))

    from src.api.main import app

    return TestClient(app)


def test_ask_without_repo_uses_offline_path(client):
    resp = client.post("/ask", json={"question": "What issues are open?"})
    assert resp.status_code == 200
    assert resp.json()["repo"] is None


def test_ask_malformed_repo_returns_422(client):
    # normalize_repo raises ValueError before any network -> mapped to 422.
    resp = client.post("/ask", json={"question": "q", "repo": "https://gitlab.com/x/y"})
    assert resp.status_code == 422


def test_ask_forwards_repo_and_token_but_hides_token(client, monkeypatch):
    seen = {}

    def _fake_run_pipeline(question, store, repo=None, token=None):
        seen["repo"], seen["token"] = repo, token
        return Trace(run_id="apitest", question=question, repo="owner/name", answer="ok")

    monkeypatch.setattr("src.api.main.run_pipeline", _fake_run_pipeline)

    resp = client.post(
        "/ask",
        json={"question": "q", "repo": "owner/name", "token": "ghp_SUPERSECRET"},
    )
    assert resp.status_code == 200
    assert seen["repo"] == "owner/name"          # raw repo forwarded
    assert seen["token"] == "ghp_SUPERSECRET"    # token unwrapped for the client
    assert "ghp_SUPERSECRET" not in resp.text    # ...but never returned
    assert resp.json()["repo"] == "owner/name"


def test_ask_unreadable_repo_returns_400(client, monkeypatch):
    def _boom(question, store, repo=None, token=None):
        raise RepoAccessError(
            "Repository 'owner/x' was not found, or it is private and the token is missing."
        )

    monkeypatch.setattr("src.api.main.run_pipeline", _boom)
    resp = client.post("/ask", json={"question": "q", "repo": "owner/x"})
    assert resp.status_code == 400
    assert "not found" in resp.json()["detail"].lower()
