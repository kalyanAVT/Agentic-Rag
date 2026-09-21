"""
Agentic RAG — FastAPI application.

Phase 0: /health endpoint only.
Later phases add /ask and trace endpoints.
"""

from fastapi import FastAPI

app = FastAPI(
    title="Agentic RAG",
    description="Multi-hop question answering over live GitHub data with memory and tracing.",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict:
    """Liveness check. Returns current build phase for quick sanity during dev."""
    return {"status": "ok", "phase": 0}
