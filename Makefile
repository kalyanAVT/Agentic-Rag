# =============================================================================
# Agentic RAG — Makefile
# =============================================================================
# Targets correspond to CLAUDE.md § Commands. Update as the project grows.
# =============================================================================

PYTHON ?= python
PIP    ?= pip
VENV   := .venv

# ---------------------------------------------------------------------------
# setup — install deps, copy .env.example → .env if missing
# ---------------------------------------------------------------------------
.PHONY: setup
setup:
	$(PYTHON) -m venv $(VENV)
	$(VENV)/Scripts/pip install --upgrade pip
	$(VENV)/Scripts/pip install -r requirements.txt
	@if not exist .env copy .env.example .env

# ---------------------------------------------------------------------------
# dev — run API locally with hot-reload
# ---------------------------------------------------------------------------
.PHONY: dev
dev:
	$(VENV)/Scripts/uvicorn src.api.main:app --reload --port 8000

# ---------------------------------------------------------------------------
# test — run test suite
# ---------------------------------------------------------------------------
.PHONY: test
test:
	$(VENV)/Scripts/pytest tests/ -v

# ---------------------------------------------------------------------------
# demo — run a canned end-to-end question (Phase 1+)
# ---------------------------------------------------------------------------
.PHONY: demo
demo:
	@echo "demo target not yet implemented — available from Phase 1 onward."

# ---------------------------------------------------------------------------
# deploy — build + push + deploy to DigitalOcean (Phase 7+)
# ---------------------------------------------------------------------------
.PHONY: deploy
deploy:
	@echo "deploy target not yet implemented — available from Phase 7 onward."
