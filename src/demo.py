"""
Demo runner -- end-to-end agentic pipeline.

Phase 2: LLM-driven planner + LLM tool-calling against seed data.
Run with: python -m src.demo
Or:       make demo
"""

from __future__ import annotations

import time
import uuid
import sys

from dotenv import load_dotenv

# Load .env BEFORE importing src modules so os.getenv("GITHUB_REPO") is available at import time
load_dotenv()

from src.agent import execute_plan_step
from src.memory.seed import seed_prior_session
from src.memory.session import SessionMemory
from src.memory.store import MemoryStore
from src.memory.writeback import extract_memories
from src.planner.planner import generate_plan
from src.synthesis.synthesizer import synthesize
from src.tracing.models import MemoryEntry, Trace

# -- Demo questions --------------------------------------------------------
# Phase 2 requires two different questions producing different plans.

DEMO_QUESTIONS = [
    "What are the most recent merged pull requests in this repository?",
    "Are there any open issues regarding reinforcement learning algorithms?",
    # Cross-session recall: retrieves a fact seeded by a "prior session"
    # (see src/memory/seed.py) and reconciles it against current evidence.
    "What did we decide about the dashboard pagination fix, and is it still on track?",
]


def run_pipeline(question: str, store: MemoryStore | None = None) -> Trace:
    """Execute the full agentic pipeline for a single question.

    Phase 4 adds memory: relevant long-term facts are retrieved before
    planning and fed into the planner + synthesis; durable new facts are
    written back after synthesis. Both ends are recorded on the trace
    (memory_used / memory_written).
    """
    run_id = str(uuid.uuid4())[:8]
    t_start = time.perf_counter_ns()

    # 0. Recall relevant long-term memory (empty if none relevant / no store)
    memory_used: list[MemoryEntry] = store.retrieve(question) if store else []

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

    # 4. Write-back: persist any durable new facts (online only; no-op offline)
    memory_written: list[MemoryEntry] = []
    if store:
        for entry in extract_memories(question, answer, evidence, run_id):
            if store.add(entry):
                memory_written.append(entry)

    timing["total_ms"] = (time.perf_counter_ns() - t_start) // 1_000_000

    # 5. Build trace
    trace = Trace(
        run_id=run_id,
        question=question,
        memory_used=memory_used,
        plan=plan,
        tool_calls=all_tool_calls,
        evidence=evidence,
        memory_written=memory_written,
        answer=answer,
        citations=citations,
        timing_ms=timing,
    )

    return trace


def print_trace(trace: Trace):
    """Pretty-print the pipeline trace."""
    def safe_print(s):
        print(str(s).encode(sys.stdout.encoding or 'ascii', 'replace').decode(sys.stdout.encoding or 'ascii'))

    sep = "=" * 72
    safe_print(f"\n{sep}")
    safe_print(f"  AGENTIC RAG -- Demo Run [{trace.run_id}]")
    safe_print(f"{sep}\n")

    # Question
    safe_print(f"[?] QUESTION: {trace.question}\n")

    # Memory recalled from prior sessions
    if trace.memory_used:
        safe_print(f"[MEMORY USED] ({len(trace.memory_used)} recalled)")
        for m in trace.memory_used:
            tags = ", ".join(m.topic_tags)
            safe_print(f"   [M] {m.text}  <tags: {tags}>")
        safe_print("")

    # Plan
    safe_print("[PLAN]")
    for i, step in enumerate(trace.plan):
        safe_print(f"   {i+1}. {step.sub_question} -> {step.tool_hint}")
    safe_print("")

    # Tool calls
    safe_print("[TOOLS]")
    for tc in trace.tool_calls:
        status = "OK" if tc.success else "FAIL"
        n_results = len(tc.result) if isinstance(tc.result, list) else 0
        safe_print(f"   [{status}] {tc.tool_name}({tc.args}) -> {n_results} results ({tc.latency_ms}ms)")
    safe_print("")

    # Evidence
    safe_print(f"[EVIDENCE] ({len(trace.evidence)} items)")
    for i, e in enumerate(trace.evidence):
        safe_print(f"   [E{i+1}] ({e.source} {e.id}): {e.text[:100]}...")
    safe_print("")

    # Answer
    safe_print("[ANSWER]")
    for line in trace.answer.split("\n"):
        safe_print(f"   {line}")
    safe_print("")

    # Citations
    if trace.citations:
        safe_print("[CITATIONS]")
        for c in trace.citations:
            safe_print(f"   {c.claim} -> {c.evidence_id} ({c.url})")
        safe_print("")

    # Memory written (new durable facts persisted this run)
    if trace.memory_written:
        safe_print(f"[MEMORY WRITTEN] ({len(trace.memory_written)} persisted)")
        for m in trace.memory_written:
            safe_print(f"   [+] {m.text}")
        safe_print("")

    # Timing
    safe_print(f"[TIMING] {trace.timing_ms}")
    safe_print(f"\n{sep}\n")


if __name__ == "__main__":
    # Long-term memory store, seeded with a few facts from a "prior session"
    # so the cross-session recall question has something to recall offline.
    store = MemoryStore()
    n_seeded = seed_prior_session(store)
    print(f"[memory] {store.count()} long-term facts available ({n_seeded} newly seeded)")

    for i, question in enumerate(DEMO_QUESTIONS):
        if i > 0:
            print("\n" + "#" * 72)
            print(f"#  DEMO QUESTION {i + 1}")
            print("#" * 72)

        trace = run_pipeline(question, store)
        print_trace(trace)

    store.close()
