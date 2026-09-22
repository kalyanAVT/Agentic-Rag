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
# deploy — build + push + deploy to DigitalOcean (Phase 7+)
# ---------------------------------------------------------------------------
.PHONY: deploy
deploy:
	@echo "deploy target not yet implemented; available from Phase 7 onward."
