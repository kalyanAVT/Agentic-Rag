"""
Planner -- LLM-driven query decomposition.

Phase 2: uses OpenAI structured output to decompose any question into
2-5 sub-questions with tool hints. Falls back to a simple heuristic
if no API key is set.

Spec: docs/ARCHITECTURE.md section 1 (Planner)
"""

from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, Field

from src.tracing.models import PlanStep


# -- Structured output schema for OpenAI -----------------------------------

class Plan(BaseModel):
    """Ordered list of sub-questions for a user question."""

    steps: list[PlanStep] = Field(
        ...,
        min_length=2,
        max_length=5,
        description="Ordered list of 2-5 sub-questions to investigate.",
    )


# -- Tool descriptions for the planner prompt ------------------------------

TOOL_DESCRIPTIONS = """Available tools (against a GitHub repository):
- search_issues(query: str) -- Search issues and PRs by keyword or label. Use for finding goals, blockers, bugs, features, or any topic-based lookup.
- get_issue(number: int) -- Get full details of a specific issue including body and all comments.
- list_pull_requests(state: str) -- List pull requests. State can be "all", "merged", or "open". Use for finding completed work, code changes, reviews.
- list_commits(since: str) -- List commits, optionally filtered by ISO date string. Use for finding recent code changes.
- list_recent_activity(since: str) -- Combined view of issues + commits since a date. Use for broad "what changed" questions."""


SYSTEM_PROMPT = f"""You are a query decomposition planner for a project analysis system.
Given a user's question about a software project, break it into 2-5 ordered
sub-questions that can each be answered by calling one of the available tools.

{TOOL_DESCRIPTIONS}

For each sub-question, optionally suggest which tool would best answer it
in the tool_hint field. Keep the plan LINEAR -- each step should be
independently answerable (no dependencies between steps).

Return a JSON object with a "steps" array."""


def generate_plan(question: str) -> list[PlanStep]:
    """
    Decompose a user question into an ordered list of sub-questions.

    Uses OpenAI structured output if available, otherwise falls back
    to a simple keyword-based heuristic.
    """
    api_key = os.getenv("OPENAI_API_KEY", "")

    if api_key and api_key != "sk-change-me":
        return _llm_plan(question, api_key)
    else:
        return _fallback_plan(question)


def _llm_plan(question: str, api_key: str) -> list[PlanStep]:
    """Use OpenAI to decompose the question via structured output."""
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    response = client.beta.chat.completions.parse(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ],
        response_format=Plan,
        temperature=0.2,
    )

    plan = response.choices[0].message.parsed
    if plan is None:
        return _fallback_plan(question)

    return plan.steps


def _fallback_plan(question: str) -> list[PlanStep]:
    """Simple keyword-based fallback when no API key is available."""
    q_lower = question.lower()
    steps: list[PlanStep] = []

    # Always start with a broad search
    steps.append(PlanStep(
        sub_question=f"What are the key topics and goals related to: {question}",
        tool_hint="search_issues",
    ))

    if any(w in q_lower for w in ["change", "update", "progress", "ship", "complete"]):
        steps.append(PlanStep(
            sub_question="What pull requests and code changes were made?",
            tool_hint="list_pull_requests",
        ))

    if any(w in q_lower for w in ["risk", "block", "issue", "problem", "concern"]):
        steps.append(PlanStep(
            sub_question="What blockers or risks have been reported?",
            tool_hint="search_issues",
        ))

    if any(w in q_lower for w in ["deadline", "date", "when", "timeline", "schedule"]):
        steps.append(PlanStep(
            sub_question="What deadlines or timeline changes occurred?",
            tool_hint="search_issues",
        ))

    if any(w in q_lower for w in ["commit", "code", "recent"]):
        steps.append(PlanStep(
            sub_question="What recent commits were made?",
            tool_hint="list_commits",
        ))

    # Ensure at least 2 steps
    if len(steps) < 2:
        steps.append(PlanStep(
            sub_question="What is the overall status and any open issues?",
            tool_hint="search_issues",
        ))

    return steps[:5]
