"""
API tests for Phase 5 observability endpoints.

Every test forces the deterministic OFFLINE path (no real LLM key) and isolates
both the memory DB and the trace directory into pytest tmp dirs, so the suite
never needs network access and never touches real ./traces or the project DB.

The offline forcing relies on two facts:
  * ``llm_enabled()`` reads the env live on each call, and get_api_key() prefers
    LLM_API_KEY then OPENAI_API_KEY -- setting LLM_API_KEY="" and
    OPENAI_API_KEY to a placeholder guarantees the fallback (no network) path.
  * ``load_dotenv()`` at import uses override=False, so it cannot clobber the
    values monkeypatch has already set in os.environ.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch, tmp_path):
    # Force offline LLM (deterministic fallbacks, no network).
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-change-me")
    # Never hit real GitHub; use mock seed data.
    monkeypatch.setenv("GITHUB_MCP_MODE", "none")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_change-me")
    # Isolate persistence.
    monkeypatch.setenv("MEMORY_DB_PATH", ":memory:")
    monkeypatch.setenv("TRACE_DIR", str(tmp_path / "traces"))

    from src.api.main import app

    return TestClient(app)


def test_health_reports_current_phase(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["phase"] == 6


def test_ask_runs_pipeline_and_returns_trace(client):
    resp = client.post(
        "/ask", json={"question": "What are the most recent merged pull requests?"}
    )
    assert resp.status_code == 200
    trace = resp.json()

    # A well-formed Trace came back.
    assert trace["run_id"]
    assert trace["question"]
    assert trace["plan"]          # planner produced steps (offline fallback plan)
    assert trace["answer"]        # synthesis produced an answer (offline fallback)
    assert "total_ms" in trace["timing_ms"]


def test_ask_then_run_is_retrievable_from_runs(client):
    run_id = client.post("/ask", json={"question": "Any open RL issues?"}).json()["run_id"]

    # It appears in the listing...
    listing = client.get("/runs")
    assert listing.status_code == 200
    assert any(r["run_id"] == run_id for r in listing.json())

    # ...and can be fetched in full by id.
    one = client.get(f"/runs/{run_id}")
    assert one.status_code == 200
    assert one.json()["run_id"] == run_id


def test_get_unknown_run_returns_404(client):
    resp = client.get("/runs/deadbeef")
    assert resp.status_code == 404


def test_ask_rejects_empty_question(client):
    # min_length=1 on the request model -> 422 before the pipeline runs.
    resp = client.post("/ask", json={"question": ""})
    assert resp.status_code == 422
