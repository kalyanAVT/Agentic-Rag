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
from src.planner.planner import generate_plan
from src.synthesis.synthesizer import synthesize
from src.tracing.models import EvidenceItem, Trace

# -- Demo questions --------------------------------------------------------
# Phase 2 requires two different questions producing different plans.

DEMO_QUESTIONS = [
    "What are the most recent merged pull requests in this repository?",
    "Are there any open issues regarding reinforcement learning algorithms?",
]


def run_pipeline(question: str) -> Trace:
    """Execute the full agentic pipeline for a single question."""
    run_id = str(uuid.uuid4())[:8]
    t_start = time.perf_counter_ns()

    # 1. LLM-driven plan
    t_plan = time.perf_counter_ns()
    plan = generate_plan(question)
    timing = {"plan_ms": (time.perf_counter_ns() - t_plan) // 1_000_000}

    # 2. Execute each plan step with LLM tool-calling
    all_evidence: list[EvidenceItem] = []
    all_tool_calls = []

    t_tools = time.perf_counter_ns()
    for step in plan:
        evidence, tool_calls = execute_plan_step(step, all_evidence)
        all_evidence.extend(evidence)
        all_tool_calls.extend(tool_calls)
    timing["tools_ms"] = (time.perf_counter_ns() - t_tools) // 1_000_000

    # Deduplicate evidence by id
    seen_ids: set[str] = set()
    unique_evidence: list[EvidenceItem] = []
    for e in all_evidence:
        if e.id not in seen_ids:
            seen_ids.add(e.id)
            unique_evidence.append(e)

    # 3. Synthesize
    t_synth = time.perf_counter_ns()
    answer, citations = synthesize(question, plan, unique_evidence)
    timing["synthesis_ms"] = (time.perf_counter_ns() - t_synth) // 1_000_000

    timing["total_ms"] = (time.perf_counter_ns() - t_start) // 1_000_000

    # 4. Build trace
    trace = Trace(
        run_id=run_id,
        question=question,
        plan=plan,
        tool_calls=all_tool_calls,
        evidence=unique_evidence,
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

    # Timing
    safe_print(f"[TIMING] {trace.timing_ms}")
    safe_print(f"\n{sep}\n")


if __name__ == "__main__":
    for i, question in enumerate(DEMO_QUESTIONS):
        if i > 0:
            print("\n" + "#" * 72)
            print(f"#  DEMO QUESTION {i + 1}")
            print("#" * 72)

        trace = run_pipeline(question)
        print_trace(trace)
