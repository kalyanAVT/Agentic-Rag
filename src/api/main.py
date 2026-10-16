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

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, SecretStr

from src.llm import LLMSettings
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
    """Body for POST /ask.

    Every secret is optional and per-request (bring-your-own-key): the UI keeps
    them in the visitor's browser and sends them with each question. They are
    unwrapped only to build clients inside the run -- never stored, logged, or
    returned.
    """

    question: str = Field(..., min_length=1, description="The multi-hop question to answer.")
    repo: str | None = Field(
        default=None,
        max_length=300,
        description=(
            "Optional GitHub repo to answer against live (URL or 'owner/name'). "
            "Omit to use the offline seed demo."
        ),
    )
    github_token: SecretStr | None = Field(
        default=None,
        description="Optional GitHub token (needed for private repos; lifts rate limits).",
    )
    llm_api_key: SecretStr | None = Field(
        default=None,
        description=(
            "Optional LLM API key. When set, llm_base_url / llm_model apply too and "
            "this run uses the caller's provider instead of the server's."
        ),
    )
    llm_base_url: str | None = Field(
        default=None,
        max_length=300,
        description="OpenAI-compatible endpoint (https, public host). Empty = OpenAI.",
    )
    llm_model: str | None = Field(default=None, max_length=200, description="Model id.")

    def llm_settings(self) -> LLMSettings | None:
        """The caller's LLM settings, or None to use the server's config. The
        base URL and model only apply together with a key."""
        key = self.llm_api_key.get_secret_value().strip() if self.llm_api_key else ""
        if not key:
            return None
        return LLMSettings(
            api_key=key,
            base_url=(self.llm_base_url or "").strip(),
            model=(self.llm_model or "").strip(),
        )


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """422 without the rejected input: FastAPI echoes it by default, which would
    send a caller's keys and tokens straight back in the error body."""
    errors = [
        {"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")}
        for e in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errors})


@app.get("/health")
def health() -> dict:
    """Liveness check. Returns current build phase for quick sanity during dev."""
    return {"status": "ok", "phase": CURRENT_PHASE}


@app.post("/ask", response_model=Trace)
def ask(req: AskRequest) -> Trace:
    """Run the agentic pipeline for one question and return the full Trace.

    A fresh MemoryStore is opened per request (SQLite; retrieval feeds the
    planner/synthesis, durable facts are written back). With a ``repo`` the run
    is scoped to live GitHub data for that repo; without one it uses the offline
    seed data. With ``llm_api_key`` the run uses the caller's own LLM provider.
    Public runs are persisted and emitted to observability, so they are
    retrievable via GET /runs/{run_id}; runs against a private repo are returned
    only to this caller (``trace.private``).
    """
    store = MemoryStore()
    github_token = (
        req.github_token.get_secret_value().strip() if req.github_token else ""
    ) or None
    try:
        return run_pipeline(
            req.question,
            store,
            repo=req.repo,
            github_token=github_token,
            llm=req.llm_settings(),
        )
    except ValueError as exc:
        # Malformed repo reference or rejected LLM base URL -> the client's fault.
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
