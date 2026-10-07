"""
Frontend-serving tests for Phase 6.

These assert the two things that can silently break when a static SPA is mounted
on the same FastAPI app as the JSON API:

  1. The single-page trace viewer is actually served (``GET /`` -> index.html,
     and its ``app.js`` / ``styles.css`` assets resolve).
  2. The catch-all static mount does NOT shadow the JSON API routes or the
     OpenAPI docs -- ``/health``, ``/runs`` and ``/docs`` must still work.

Offline forcing mirrors tests/test_api_runs.py so no network or real key is used.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


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


def test_root_serves_index_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    body = resp.text
    assert "Agentic RAG" in body
    assert 'src="app.js"' in body  # the SPA script is wired in


def test_static_assets_resolve(client):
    js = client.get("/app.js")
    assert js.status_code == 200
    assert "renderTrace" in js.text  # our client code, not a 404 page

    css = client.get("/styles.css")
    assert css.status_code == 200
    assert "text/css" in css.headers["content-type"]


def test_static_mount_does_not_shadow_json_api(client):
    # The catch-all "/" mount must be matched AFTER the JSON routes.
    from src.api.main import CURRENT_PHASE

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["phase"] == CURRENT_PHASE

    runs = client.get("/runs")
    assert runs.status_code == 200
    assert isinstance(runs.json(), list)


def test_openapi_docs_still_served(client):
    # FastAPI's docs routes are registered before the mount, so they survive.
    assert client.get("/openapi.json").status_code == 200
