"""
Demo runner -- end-to-end agentic pipeline.

Runs a few canned multi-hop questions through the shared pipeline
(``src/pipeline``) and pretty-prints each Trace. The pipeline itself now also
persists every Trace to TRACE_DIR (Phase 5), so after ``make demo`` the same
runs are retrievable via the API's GET /runs.

Run with: python -m src.demo    (or: make demo)
"""

from __future__ import annotations

import sys

from dotenv import load_dotenv

# Load .env BEFORE importing src modules so os.getenv(...) is available at
# import time (e.g. GITHUB_REPO read by the tool layer).
load_dotenv()

from src.memory.seed import seed_prior_session
from src.memory.store import MemoryStore
from src.pipeline import run_pipeline
from src.tracing.models import Trace

# -- Demo questions --------------------------------------------------------
# Phase 2 requires two different questions producing different plans.

DEMO_QUESTIONS = [
    "What are the most recent merged pull requests in this repository?",
    # Multi-hop: combines a blockers search (issues) with the PRs that address
    # them -- exercises 2+ tools and cross-references issue #3 <-> PR #103.
    "Which open issues are blocking the Q3 release, and are there any pull requests addressing them?",
    # Cross-session recall: retrieves a fact seeded by a "prior session"
    # (see src/memory/seed.py) and reconciles it against current evidence.
    "What did we decide about the dashboard pagination fix, and is it still on track?",
]


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
