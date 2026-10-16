"""
End-to-end agentic pipeline: memory recall -> plan -> tool-calling -> synthesis
-> selective write-back -> structured Trace.

Extracted from ``src/demo.py`` so the CLI demo and the FastAPI app (``src/api``)
drive the *exact same* pipeline -- the API is now a first-class consumer, not a
demo detail. Phase 5 adds two side effects at the end of every run, both
defensive (they can never break a run):

  * persist the Trace as JSON via ``TraceStore`` -- the self-contained
    observability half the API / frontend read back from;
  * emit the Trace to Langfuse if configured (``emit_trace`` is a no-op offline).
"""

from __future__ import annotations

import logging
import time
import uuid

from contextlib import ExitStack

from src.agent import execute_plan_step
from src.llm import LLMSettings, llm_context, validate_base_url
from src.memory.session import SessionMemory
from src.memory.store import MemoryStore
from src.memory.writeback import extract_memories
from src.planner.planner import generate_plan
from src.synthesis.synthesizer import synthesize
from src.tools.context import github_context
from src.tools.github_tools import preflight_repo
from src.tools.repo import normalize_repo
from src.tracing.models import MemoryEntry, Trace
from src.tracing.observability import emit_trace
from src.tracing.store import TraceStore

logger = logging.getLogger(__name__)


def run_pipeline(
    question: str,
    store: MemoryStore | None = None,
    repo: str | None = None,
    github_token: str | None = None,
    llm: LLMSettings | None = None,
) -> Trace:
    """Execute the full agentic pipeline for a single question.

    Phase 4 adds memory: relevant long-term facts are retrieved before planning
    and fed into the planner + synthesis; durable new facts are written back
    after synthesis (both ends recorded on the trace). Phase 5 persists the
    resulting Trace and ships it to the observability backend, so every run --
    demo or API -- is retrievable afterwards.

    ``repo`` (any GitHub repo, as a URL or "owner/name") scopes the run to live
    GitHub data for THAT repo, with an optional ``github_token`` for private
    repos. With no repo the run stays on the offline seed path. ``llm`` carries a
    visitor's own key / base URL / model (bring-your-own-key); None uses the
    server's config.

    A run against a PRIVATE repo is marked ``private``: it is returned to the
    caller but never persisted, written to shared memory, or sent to Langfuse.

    SECURITY: the GitHub token and LLM key are used only to build clients for
    this request -- never placed on the Trace, evidence, tool calls, or memory.
    """
    normalized_repo = normalize_repo(repo) if repo else None
    if llm is not None and llm.base_url:
        # The server will send the visitor's key to this URL -- check it first.
        llm = LLMSettings(
            api_key=llm.api_key, base_url=validate_base_url(llm.base_url), model=llm.model
        )

    private = False
    if normalized_repo:
        # Fail fast, and with a clear message, if the repo is unreadable -- before
        # the pipeline spends any LLM calls or tool requests on it.
        private = bool(preflight_repo(normalized_repo, github_token))

    with ExitStack() as stack:
        if normalized_repo:
            stack.enter_context(github_context(normalized_repo, github_token))
        stack.enter_context(llm_context(llm))
        return _execute(question, store, normalized_repo, private)


def _execute(
    question: str, store: MemoryStore | None, repo: str | None, private: bool
) -> Trace:
    run_id = str(uuid.uuid4())[:8]
    t_start = time.perf_counter_ns()

    # 0. Recall relevant long-term memory -- only facts about THIS repo
    #    ("" = the offline seed demo), so no cross-repo [M#] citations.
    memory_used: list[MemoryEntry] = (
        store.retrieve(question, repo=repo or "") if store else []
    )

    # 1. LLM-driven plan (memory-aware)
    t_plan = time.perf_counter_ns()
    plan = generate_plan(question, memory_used)
    timing = {"plan_ms": (time.perf_counter_ns() - t_plan) // 1_000_000}

    # 2. Execute each plan step; SessionMemory holds working evidence (deduped)
    session = SessionMemory()
    all_tool_calls = []

    t_tools = time.perf_counter_ns()
    for step in plan:
        session.record_step(step)
        evidence, tool_calls = execute_plan_step(step, session.evidence)
        session.add_evidence(evidence)
        all_tool_calls.extend(tool_calls)
    timing["tools_ms"] = (time.perf_counter_ns() - t_tools) // 1_000_000

    evidence = session.evidence

    # 3. Synthesize (memory-aware)
    t_synth = time.perf_counter_ns()
    answer, citations = synthesize(question, plan, evidence, memory_used)
    timing["synthesis_ms"] = (time.perf_counter_ns() - t_synth) // 1_000_000

    # 4. Write-back: persist any durable new facts (online only; no-op offline).
    #    Facts are tagged with their repo. Private runs never write: shared
    #    memory must not hold a private repo's contents.
    memory_written: list[MemoryEntry] = []
    if store and not private:
        for entry in extract_memories(question, answer, evidence, run_id):
            entry = entry.model_copy(update={"repo": repo or ""})
            if store.add(entry):
                memory_written.append(entry)

    timing["total_ms"] = (time.perf_counter_ns() - t_start) // 1_000_000

    # 5. Build trace
    trace = Trace(
        run_id=run_id,
        question=question,
        repo=repo,
        private=private,
        memory_used=memory_used,
        plan=plan,
        tool_calls=all_tool_calls,
        evidence=evidence,
        memory_written=memory_written,
        answer=answer,
        citations=citations,
        timing_ms=timing,
    )

    # 6. Observability side effects -- must never break a run. Skipped for
    #    private runs: /runs and Langfuse are shared with other people.
    if not private:
        _persist_trace(trace)
        emit_trace(trace)  # exception-safe + no-op when Langfuse is not configured

    return trace


def _persist_trace(trace: Trace) -> None:
    """Write the trace to the TraceStore, swallowing any I/O error so a failure
    to persist never takes down the run itself."""
    try:
        path = TraceStore().save(trace)
        logger.debug("Trace %s persisted to %s", trace.run_id, path)
    except Exception as exc:  # noqa: BLE001 - persistence must not break a run
        logger.warning("Failed to persist trace %s (%s).", trace.run_id, exc)
