"""
Agentic RAG -- FastAPI application.

Phase 5 (observability) exposes the pipeline and its traces over HTTP:
  * POST /ask            -- run the full pipeline for a question, persist + emit
                            the Trace, and return it as JSON.
  * GET  /runs           -- list summaries of every persisted run (newest first).
  * GET  /runs/{run_id}  -- fetch one run's full Trace JSON.

The GET endpoints read from the same on-disk TraceStore that every run writes to,
so traces are retrievable from our own API independent of any third-party
dashboard (Phase 5 definition of done). See docs/ARCHITECTURE.md sections 5-6.

Phase 6 (frontend) mounts the static single-page trace viewer (``frontend/``) at
``/`` on this same app, so the whole demo ships as one container.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

# Load .env before importing pipeline modules that read env at import time.
load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, SecretStr

from src.memory.store import MemoryStore
from src.pipeline import run_pipeline
from src.tools.repo import RepoAccessError
from src.tracing.models import Trace
from src.tracing.store import TraceStore

# Current build phase, surfaced by GET /health. One constant so the phase is
# bumped in a single place (tests assert against it, not a magic number).
CURRENT_PHASE = 8

app = FastAPI(
    title="Agentic RAG",
    description="Multi-hop question answering over live GitHub data with memory and tracing.",
    version="0.8.0",
)


class AskRequest(BaseModel):
    """Body for POST /ask."""

    question: str = Field(..., min_length=1, description="The multi-hop question to answer.")
    repo: str | None = Field(
        default=None,
        description=(
            "Optional GitHub repo to answer against live (URL or 'owner/name'). "
            "Omit to use the offline seed demo."
        ),
    )
    token: SecretStr | None = Field(
        default=None,
        description=(
            "Optional GitHub token for a private repo. Used only to build the "
            "GitHub client for this request -- never stored, logged, or returned."
        ),
    )


@app.get("/health")
def health() -> dict:
    """Liveness check. Returns current build phase for quick sanity during dev."""
    return {"status": "ok", "phase": CURRENT_PHASE}


@app.post("/ask", response_model=Trace)
def ask(req: AskRequest) -> Trace:
    """Run the agentic pipeline for one question and return the full Trace.

    A fresh MemoryStore is opened per request (SQLite; retrieval feeds the
    planner/synthesis, durable facts are written back). With a ``repo`` the run
    is scoped to live GitHub data for that repo (optionally private, via
    ``token``); without one it uses the offline seed data. The pipeline persists
    the Trace and emits it to observability as a side effect, so the returned run
    is immediately retrievable via GET /runs/{run_id}.

    SECURITY: ``token`` is unwrapped only to build the GitHub client inside the
    run; it is absent from the request log, the Trace, and every response model.
    """
    store = MemoryStore()
    token = req.token.get_secret_value() if req.token else None
    try:
        return run_pipeline(req.question, store, repo=req.repo, token=token)
    except ValueError as exc:
        # Malformed repo reference -> the client's fault.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RepoAccessError as exc:
        # Repo missing, private without a valid token, or rate-limited.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        store.close()


@app.get("/runs")
def list_runs() -> list[dict]:
    """Summaries of every persisted run (run_id, question, answer preview, ...)."""
    return TraceStore().list_runs()


@app.get("/runs/{run_id}", response_model=Trace)
def get_run(run_id: str) -> Trace:
    """Fetch one persisted run's full Trace, or 404 if there is no such run."""
    trace = TraceStore().load(run_id)
    if trace is None:
        raise HTTPException(status_code=404, detail=f"No trace found for run_id {run_id!r}")
    return trace


# --- Static frontend (Phase 6) --------------------------------------------
# Mounted LAST, on purpose: Starlette matches routes in registration order, so
# the JSON API routes above (plus FastAPI's own /docs and /openapi.json, added
# at app construction) are matched first. This catch-all mount then serves the
# single-page trace viewer for everything else, with html=True resolving "/" to
# frontend/index.html. Guarded so the API still boots if the dir is missing.
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
