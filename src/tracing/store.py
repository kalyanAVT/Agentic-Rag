"""
Persist and retrieve Trace objects as JSON files on disk.

Phase 5: every run's Trace is written to TRACE_DIR (default ./traces) as
``<timestamp>-<run_id>.json`` and can be listed / fetched back by run_id. This
is the *self-contained* half of observability -- the API (GET /runs,
GET /runs/{run_id}) and, later, the frontend read from here, with no dependency
on any third-party dashboard being reachable during a live demo (see
docs/ARCHITECTURE.md section 5).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from src.tracing.models import Trace

DEFAULT_TRACE_DIR = "traces"
_PREVIEW_CHARS = 200


class TraceStore:
    """Flat-file JSON store for run traces. Intentionally infra-free (see
    ARCHITECTURE.md "Extension points" -- swap for object storage / a DB to
    scale). The directory is resolved at construction from ``trace_dir`` or the
    ``TRACE_DIR`` env var, so tests and deployments can point it anywhere.
    """

    def __init__(self, trace_dir: str | os.PathLike | None = None) -> None:
        self.dir = Path(trace_dir or os.getenv("TRACE_DIR", DEFAULT_TRACE_DIR))

    def save(self, trace: Trace) -> Path:
        """Write ``trace`` to ``<dir>/<utc-timestamp>-<run_id>.json`` and return
        the path. Creates the directory if needed."""
        self.dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = self.dir / f"{ts}-{trace.run_id}.json"
        path.write_text(trace.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load(self, run_id: str) -> Trace | None:
        """Return the (newest) persisted Trace for ``run_id``, or None if absent
        or unparseable."""
        if not self.dir.exists():
            return None
        for path in sorted(self.dir.glob(f"*-{run_id}.json"), reverse=True):
            try:
                return Trace.model_validate_json(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 - skip corrupt files, keep listing usable
                continue
        return None

    def list_runs(self) -> list[dict]:
        """Return lightweight summaries of every persisted run, newest first.

        Summaries (not full traces) keep the listing cheap for the API/frontend;
        callers fetch the full Trace by run_id only when they need it.
        """
        if not self.dir.exists():
            return []
        summaries: list[dict] = []
        for path in sorted(self.dir.glob("*.json"), reverse=True):
            try:
                trace = Trace.model_validate_json(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 - ignore corrupt/partial files
                continue
            summaries.append(
                {
                    "run_id": trace.run_id,
                    "question": trace.question,
                    "answer_preview": trace.answer[:_PREVIEW_CHARS],
                    "n_evidence": len(trace.evidence),
                    "n_citations": len(trace.citations),
                    "total_ms": trace.timing_ms.get("total_ms", 0),
                    "file": path.name,
                }
            )
        return summaries
