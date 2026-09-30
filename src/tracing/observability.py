"""
Optional third-party observability (Langfuse) for agent runs.

Modeled deliberately on ``src/llm.py``: env-gated, lazily imported, and a total
no-op when unconfigured -- so ``make demo`` runs offline with zero keys, and a
missing SDK or a network/auth error can *never* break a run. Observability is a
side channel; the pipeline's correctness must not depend on it.

When ``LANGFUSE_PUBLIC_KEY`` + ``LANGFUSE_SECRET_KEY`` are set, each run is shipped
to Langfuse as one trace with child spans (planner, each tool call, synthesis),
satisfying the Phase 5 "shows up in the dashboard" requirement. The structured
Trace JSON persisted by ``TraceStore`` is the independent, always-on half.

Langfuse is the recommended backend (open-source, free cloud tier, self-hostable
-- fits the DigitalOcean deploy story). LangSmith could slot in behind the same
``emit_trace`` seam via its ``@traceable``/Client API if preferred later.
"""

from __future__ import annotations

import logging
import os

from src.tracing.models import Trace

logger = logging.getLogger(__name__)

# Placeholder values from .env.example that mean "not really configured".
_PLACEHOLDERS = {"", "sk-lf-change-me", "pk-lf-change-me"}


def langfuse_enabled() -> bool:
    """True only when both Langfuse keys are set to real (non-placeholder) values."""
    public = os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
    secret = os.getenv("LANGFUSE_SECRET_KEY", "").strip()
    return (
        public not in _PLACEHOLDERS
        and secret not in _PLACEHOLDERS
        and bool(public)
        and bool(secret)
    )


def emit_trace(trace: Trace) -> bool:
    """Ship a completed Trace to Langfuse if configured. Returns True if emitted.

    Never raises: any missing dependency, auth, or network error is swallowed and
    logged, because observability must not be able to break the pipeline.
    """
    if not langfuse_enabled():
        return False
    try:
        return _emit_langfuse(trace)
    except Exception as exc:  # noqa: BLE001 - observability must never break a run
        logger.warning("Langfuse emit failed (%s); continuing without it.", exc)
        return False


def _emit_langfuse(trace: Trace) -> bool:
    """Map our Trace onto a Langfuse trace + spans. Imported lazily so the SDK is
    only required when the integration is actually switched on."""
    from langfuse import Langfuse  # lazy: only needed when enabled

    client = Langfuse()  # reads LANGFUSE_PUBLIC_KEY / SECRET_KEY / HOST from env

    lf_trace = client.trace(
        name="agentic-rag-run",
        input={"question": trace.question},
        output={"answer": trace.answer},
        metadata={
            "run_id": trace.run_id,
            "n_evidence": len(trace.evidence),
            "n_citations": len(trace.citations),
            "timing_ms": trace.timing_ms,
            "memory_used": [m.text for m in trace.memory_used],
            "memory_written": [m.text for m in trace.memory_written],
        },
    )

    # Planner as one span (logged even if later stages fail).
    lf_trace.span(
        name="planner",
        input={"question": trace.question},
        output={"plan": [s.sub_question for s in trace.plan]},
    ).end()

    # Each tool call as its own span with args / result-size / latency.
    for tc in trace.tool_calls:
        n_results = len(tc.result) if isinstance(tc.result, list) else 0
        lf_trace.span(
            name=f"tool:{tc.tool_name}",
            input=tc.args,
            output={"n_results": n_results, "success": tc.success},
            metadata={"latency_ms": tc.latency_ms},
        ).end()

    # Synthesis as the final span.
    lf_trace.span(
        name="synthesis",
        input={"n_evidence": len(trace.evidence)},
        output={
            "answer": trace.answer,
            "citations": [c.evidence_id for c in trace.citations],
        },
    ).end()

    client.flush()  # ensure delivery before the process may exit (CLI runs)
    logger.info("Trace %s emitted to Langfuse.", trace.run_id)
    return True
