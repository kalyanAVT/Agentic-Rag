# =============================================================================
# Agentic RAG — Makefile
# =============================================================================
# Targets correspond to CLAUDE.md § Commands. Update as the project grows.
# Cross-platform: selects the venv's Scripts/ (Windows) or bin/ (Linux/macOS).
# =============================================================================

PYTHON ?= python
VENV   := .venv

ifeq ($(OS),Windows_NT)
VENV_BIN := $(VENV)/Scripts
else
VENV_BIN := $(VENV)/bin
endif

# ---------------------------------------------------------------------------
# setup — create venv, install deps, copy .env.example -> .env if missing
# ---------------------------------------------------------------------------
.PHONY: setup
setup:
	$(PYTHON) -m venv $(VENV)
	$(VENV_BIN)/pip install --upgrade pip
	$(VENV_BIN)/pip install -r requirements.txt
	$(PYTHON) -c "import os, shutil; shutil.copy('.env.example', '.env') if not os.path.exists('.env') else print('.env exists, leaving as-is')"

# ---------------------------------------------------------------------------
# dev — run API locally with hot-reload
# ---------------------------------------------------------------------------
.PHONY: dev
dev:
	$(VENV_BIN)/uvicorn src.api.main:app --reload --port 8000

# ---------------------------------------------------------------------------
# test — run test suite
# ---------------------------------------------------------------------------
.PHONY: test
test:
	$(VENV_BIN)/pytest tests/ -v

# ---------------------------------------------------------------------------
# demo — run a canned end-to-end question (Phase 1+)
# ---------------------------------------------------------------------------
.PHONY: demo
demo:
	$(VENV_BIN)/python -m src.demo

# ---------------------------------------------------------------------------
# seed-memory — populate long-term memory with prior-session facts (Phase 4)
# ---------------------------------------------------------------------------
.PHONY: seed-memory
seed-memory:
	$(VENV_BIN)/python scripts/seed_memory.py

# ---------------------------------------------------------------------------
# Container image (Phase 7) — build from the repo root; Dockerfile is in infra/.
# ---------------------------------------------------------------------------
IMAGE ?= agentic-rag:latest

.PHONY: docker-build
docker-build:
	docker build -f infra/Dockerfile -t $(IMAGE) .

.PHONY: docker-run
docker-run:
	docker run --rm -p 8000:8000 $(IMAGE)

.PHONY: compose-up
compose-up:
	docker compose -f infra/docker-compose.yml up --build

.PHONY: compose-down
compose-down:
	docker compose -f infra/docker-compose.yml down

# ---------------------------------------------------------------------------
# deploy — (re)deploy to DigitalOcean App Platform from infra/do-app.yaml.
# Requires doctl authenticated (`doctl auth init`) + GitHub connected to DO.
# See docs/DEPLOYMENT.md. --upsert creates the app on first run, updates after.
# ---------------------------------------------------------------------------
.PHONY: deploy
deploy:
	@command -v doctl >/dev/null 2>&1 || { echo "doctl not found — install it and run 'doctl auth init' first (see docs/DEPLOYMENT.md)"; exit 1; }
	doctl apps create --spec infra/do-app.yaml --upsert
