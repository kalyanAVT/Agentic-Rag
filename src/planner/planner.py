"""
Planner -- LLM-driven query decomposition.

Phase 2: uses OpenAI structured output to decompose any question into
2-5 sub-questions with tool hints. Falls back to a simple heuristic
if no API key is set.

Spec: docs/ARCHITECTURE.md section 1 (Planner)
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from src.llm import get_client, get_model, llm_enabled
from src.tracing.models import MemoryEntry, PlanStep

logger = logging.getLogger(__name__)


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


# Generic topic tags that don't help target a search.
_GENERIC_TAGS = {"priority", "preference"}


def _memory_topic(memory: list[MemoryEntry]) -> str:
    """Derive a short, searchable topic string from the top memory entry's tags.

    Prefer distinctive, artifact-like tags (e.g. "pr-103", "issue-3") that target
    a search precisely over broad single words, then keep the top two -- this
    keeps the offline reconcile step focused on the specific work item rather
    than every issue that happens to share a common word.
    """
    if not memory:
        return ""
    tags = [t for t in memory[0].topic_tags if t.lower() not in _GENERIC_TAGS]
    tags = tags or memory[0].topic_tags
    # Stable sort: tags containing a digit (issue/PR ids) sort ahead of the rest.
    tags = sorted(tags, key=lambda t: 0 if any(ch.isdigit() for ch in t) else 1)
    return ", ".join(tags[:2])


def _memory_block(memory: list[MemoryEntry] | None) -> str:
    """Format relevant long-term memory for inclusion in the planner prompt."""
    if not memory:
        return ""
    lines = ["Relevant facts recalled from prior sessions (build on these where helpful):"]
    lines += [f"- {m.text}" for m in memory]
    return "\n".join(lines)


def generate_plan(
    question: str,
    memory: list[MemoryEntry] | None = None,
) -> list[PlanStep]:
    """
    Decompose a user question into an ordered list of sub-questions.

    Uses OpenAI structured output if available, otherwise falls back to a
    simple keyword-based heuristic. Any relevant long-term `memory` entries are
    surfaced to the planner so decomposition can build on what prior sessions
    already established (see docs/ARCHITECTURE.md section 3).
    """
    if llm_enabled():
        return _llm_plan(question, memory)
    return _fallback_plan(question, memory)


def _llm_plan(
    question: str,
    memory: list[MemoryEntry] | None = None,
) -> list[PlanStep]:
    """Decompose the question via an OpenAI-compatible LLM (structured output)."""
    user_content = question
    mem_block = _memory_block(memory)
    if mem_block:
        user_content = f"{mem_block}\n\nQuestion: {question}"

    client = get_client()
    try:
        response = client.beta.chat.completions.parse(
            model=get_model(),
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            response_format=Plan,
            temperature=0.2,
        )
    except Exception as exc:  # noqa: BLE001 - any API failure degrades gracefully
        logger.warning(
            "Planner LLM call failed (%s); using offline fallback.", exc
        )
        return _fallback_plan(question, memory)

    plan = response.choices[0].message.parsed
    if plan is None:
        return _fallback_plan(question, memory)

    return plan.steps


def _fallback_plan(
    question: str,
    memory: list[MemoryEntry] | None = None,
) -> list[PlanStep]:
    """Simple keyword-based fallback when no API key is available."""
    q_lower = question.lower()
    steps: list[PlanStep] = []

    # Always start with a broad search
    steps.append(PlanStep(
        sub_question=f"What are the key topics and goals related to: {question}",
        tool_hint="search_issues",
    ))

    # If prior memory is relevant, reconcile it against the current state --
    # this is what makes the cross-session recall visible in the plan itself.
    if memory:
        topic = _memory_topic(memory)
        steps.append(PlanStep(
            sub_question=f"{topic}: current status and whether still on track",
            tool_hint="search_issues",
        ))

    if any(w in q_lower for w in ["pull request", "merged", "merge", "review"]):
        steps.append(PlanStep(
            sub_question="Which pull requests are relevant (merged or open)?",
            tool_hint="list_pull_requests",
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
