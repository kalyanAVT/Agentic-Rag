"""
Demo runner -- end-to-end agentic pipeline.

Phase 2: LLM-driven planner + LLM tool-calling against seed data.
Run with: python -m src.demo
Or:       make demo
"""

from __future__ import annotations

import time
import uuid

from dotenv import load_dotenv

from src.agent import execute_plan_step
from src.planner.planner import generate_plan
from src.synthesis.synthesizer import synthesize
from src.tracing.models import EvidenceItem, Trace

# Load .env so OPENAI_API_KEY is available
load_dotenv()

# -- Demo questions --------------------------------------------------------
# Phase 2 requires two different questions producing different plans.

DEMO_QUESTIONS = [
    "Summarize what changed in Project X this quarter and identify major risks.",
    "What deadlines changed for Project X, and why?",
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


def print_trace(trace: Trace) -> None:
    """Pretty-print the trace to stdout."""
    sep = "=" * 72

    print(f"\n{sep}")
    print(f"  AGENTIC RAG -- Demo Run [{trace.run_id}]")
    print(f"{sep}\n")

    # Question
    print(f"[?] QUESTION: {trace.question}\n")

    # Plan
    print("[PLAN]")
    for i, step in enumerate(trace.plan):
        hint = f" -> {step.tool_hint}" if step.tool_hint else ""
        print(f"   {i+1}. {step.sub_question}{hint}")
    print()

    # Tool calls
    print("[TOOLS]")
    for tc in trace.tool_calls:
        status = "OK" if tc.success else "FAIL"
        n_results = len(tc.result) if isinstance(tc.result, list) else 0
        print(f"   [{status}] {tc.tool_name}({tc.args}) -> {n_results} results ({tc.latency_ms}ms)")
    print()

    # Evidence
    print(f"[EVIDENCE] ({len(trace.evidence)} items)")
    for i, e in enumerate(trace.evidence):
        print(f"   [E{i+1}] ({e.source} {e.id}): {e.text[:100]}...")
    print()

    # Answer
    print("[ANSWER]")
    for line in trace.answer.split("\n"):
        print(f"   {line}")
    print()

    # Citations
    if trace.citations:
        print("[CITATIONS]")
        for c in trace.citations:
            print(f"   {c.claim} -> {c.evidence_id} ({c.url})")
        print()

    # Timing
    print(f"[TIMING] {trace.timing_ms}")
    print(f"\n{sep}\n")


if __name__ == "__main__":
    for i, question in enumerate(DEMO_QUESTIONS):
        if i > 0:
            print("\n" + "#" * 72)
            print(f"#  DEMO QUESTION {i + 1}")
            print("#" * 72)

        trace = run_pipeline(question)
        print_trace(trace)
