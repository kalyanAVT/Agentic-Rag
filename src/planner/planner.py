"""
Planner — query decomposition.

Phase 1: returns a hardcoded 3-step plan for the canned demo question.
Phase 2 replaces this with an LLM-driven planner.
"""

from __future__ import annotations

from src.tracing.models import PlanStep


def generate_plan(question: str) -> list[PlanStep]:
    """
    Decompose a user question into an ordered list of sub-questions.

    Phase 1: ignores the actual question and returns a fixed plan targeting
    the canned demo question ("Summarize what changed in Project X this
    quarter and identify major risks.").
    """
    return [
        PlanStep(
            sub_question="What were Project X's goals and milestones this quarter?",
            tool_hint="search_issues",
        ),
        PlanStep(
            sub_question="What tasks were completed or changed this quarter?",
            tool_hint="list_pull_requests",
        ),
        PlanStep(
            sub_question="What blockers or risks were reported?",
            tool_hint="search_issues",
        ),
    ]
