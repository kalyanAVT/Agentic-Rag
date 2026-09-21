"""
Demo runner — end-to-end pipeline for Phase 1.

Run with: python -m src.demo
Or:       make demo
"""

from __future__ import annotations

import time
import uuid

from dotenv import load_dotenv

from src.planner.planner import generate_plan
from src.synthesis.synthesizer import synthesize
from src.tools.mock_tools import call_tool
from src.tracing.models import EvidenceItem, Trace

# Load .env so OPENAI_API_KEY is available for synthesis
load_dotenv()

# ── The canned demo question ────────────────────────────────────────────────
DEMO_QUESTION = (
    "Summarize what changed in Project X this quarter and identify major risks."
)

# ── Tool-call routing for the hardcoded plan ────────────────────────────────
# Maps tool_hint from PlanStep to (tool_name, args) for Phase 1.
# In Phase 2, the LLM decides this dynamically.
TOOL_DISPATCH = {
    0: ("search_issues", {"query": "goals milestones planning"}),
    1: ("list_pull_requests", {"state": "all"}),
    2: ("search_issues", {"query": "blocker"}),
}


def run_demo() -> Trace:
    """Execute the full hardcoded pipeline and return the trace."""
    run_id = str(uuid.uuid4())[:8]
    t_start = time.perf_counter_ns()

    # 1. Plan
    t_plan = time.perf_counter_ns()
    plan = generate_plan(DEMO_QUESTION)
    timing = {"plan_ms": (time.perf_counter_ns() - t_plan) // 1_000_000}

    # 2. Execute tools for each plan step
    all_evidence: list[EvidenceItem] = []
    all_tool_calls = []

    t_tools = time.perf_counter_ns()
    for i, step in enumerate(plan):
        tool_name, args = TOOL_DISPATCH.get(i, ("search_issues", {"query": step.sub_question}))
        evidence, tool_call = call_tool(tool_name, args)
        all_evidence.extend(evidence)
        all_tool_calls.append(tool_call)
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
    answer, citations = synthesize(DEMO_QUESTION, plan, unique_evidence)
    timing["synthesis_ms"] = (time.perf_counter_ns() - t_synth) // 1_000_000

    timing["total_ms"] = (time.perf_counter_ns() - t_start) // 1_000_000

    # 4. Build trace
    trace = Trace(
        run_id=run_id,
        question=DEMO_QUESTION,
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
    trace = run_demo()
    print_trace(trace)
