"""
Phase 7 deployment-config tests.

These validate the containerization + DigitalOcean config STATICALLY -- no Docker
daemon or network required -- so CI (and this machine, where the Docker daemon may
be down) can still guard the deploy surface. PyYAML ships with uvicorn[standard],
so parsing the specs adds no new dependency.

They assert the invariants that would silently break a deploy:
  * the image serves the real app (uvicorn src.api.main:app) as non-root, honoring
    App Platform's injected $PORT;
  * .env is excluded from the build context (no secrets baked into the image);
  * compose builds the SAME Dockerfile and persists /data;
  * the App Platform spec probes /health and ships offline-safe env sentinels, so a
    fresh deploy comes up green before any real key is added.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_dockerfile_serves_app_as_nonroot():
    df = (ROOT / "infra" / "Dockerfile").read_text(encoding="utf-8")
    assert "python:3.11-slim" in df              # slim base per DEPLOYMENT.md
    assert "uvicorn src.api.main:app" in df       # runs the real app
    assert "--host 0.0.0.0" in df                 # reachable inside a container
    assert "USER appuser" in df                   # not running as root
    assert "${PORT:-8000}" in df                  # honors App Platform's $PORT


def test_dockerignore_keeps_secrets_and_bloat_out():
    lines = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    entries = {ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")}
    assert ".env" in entries                      # never ship secrets
    assert ".venv/" in entries
    assert "traces/" in entries


def test_compose_builds_same_image_and_persists_data():
    compose = yaml.safe_load(
        (ROOT / "infra" / "docker-compose.yml").read_text(encoding="utf-8")
    )
    api = compose["services"]["api"]
    assert api["build"]["dockerfile"] == "infra/Dockerfile"
    assert api["build"]["context"] == ".."
    # memory + traces persisted onto the mounted volume
    assert api["environment"]["MEMORY_DB_PATH"].startswith("/data")
    assert api["environment"]["TRACE_DIR"].startswith("/data")
    assert any(v.startswith("agentic-data:") for v in api["volumes"])


def test_do_app_spec_is_valid_and_offline_safe():
    spec = yaml.safe_load((ROOT / "infra" / "do-app.yaml").read_text(encoding="utf-8"))
    assert spec["name"]
    (service,) = spec["services"]                 # exactly one service
    assert service["dockerfile_path"] == "infra/Dockerfile"
    assert service["health_check"]["http_path"] == "/health"
    envs = {e["key"]: e for e in service["envs"]}
    # A fresh deploy must run OFFLINE (placeholder key) -> deterministic fallbacks.
    assert envs["OPENAI_API_KEY"]["value"] == "sk-change-me"
    assert envs["OPENAI_API_KEY"]["type"] == "SECRET"
    assert envs["GITHUB_MCP_MODE"]["value"] == "none"


def test_render_blueprint_is_valid_and_offline_safe():
    spec = yaml.safe_load((ROOT / "render.yaml").read_text(encoding="utf-8"))
    (service,) = spec["services"]              # exactly one service
    assert service["type"] == "web"
    assert service["runtime"] == "docker"
    assert service["dockerfilePath"] == "./infra/Dockerfile"
    assert service["dockerContext"] == "."     # build from repo root
    assert service["healthCheckPath"] == "/health"
    envs = {e["key"]: e["value"] for e in service["envVars"]}
    # A fresh deploy must run OFFLINE (placeholder key) -> deterministic fallbacks.
    assert envs["OPENAI_API_KEY"] == "sk-change-me"
    assert envs["GITHUB_MCP_MODE"] == "none"
