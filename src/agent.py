"""
Agent executor -- LLM-driven tool calling loop.

Phase 2: the model decides which tool to call for each sub-question,
using OpenAI's native function/tool-calling. Still runs against
the local seed data (mock tools).

Spec: docs/ARCHITECTURE.md section 2 (Tool layer)
"""

from __future__ import annotations

import os
import time
from typing import Any

from src.tools.mock_tools import TOOL_REGISTRY, call_tool
from src.tracing.models import EvidenceItem, PlanStep, ToolCall


# -- OpenAI tool definitions -----------------------------------------------
# These describe the mock tools in the format OpenAI's tool-calling expects.

OPENAI_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_issues",
            "description": (
                "Search GitHub issues and PRs by keyword or label. "
                "Returns matching issues with title, body, labels, state, and comments."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query -- keywords, labels, or topic to search for.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_issue",
            "description": (
                "Get full details of a specific issue by number, "
                "including body and all comments."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "number": {
                        "type": "integer",
                        "description": "The issue number to retrieve.",
                    },
                },
                "required": ["number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_pull_requests",
            "description": (
                "List pull requests filtered by state. "
                "Returns PRs with title, body, review comments, and linked issues."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "state": {
                        "type": "string",
                        "enum": ["all", "merged", "open"],
                        "description": "Filter PRs by state.",
                    },
                },
                "required": ["state"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_commits",
            "description": (
                "List commits, optionally filtered by date. "
                "Returns commit messages, authors, and timestamps."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "since": {
                        "type": "string",
                        "description": "ISO date string (e.g. '2026-07-01') to filter commits from. Empty string for all.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_recent_activity",
            "description": (
                "Combined view of recent issues and commits since a date. "
                "Use for broad 'what changed recently' questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "since": {
                        "type": "string",
                        "description": "ISO date string to filter activity from.",
                    },
                },
                "required": ["since"],
            },
        },
    },
]


def execute_plan_step(
    step: PlanStep,
    prior_evidence: list[EvidenceItem],
) -> tuple[list[EvidenceItem], list[ToolCall]]:
    """
    Execute a single plan step using LLM tool-calling.

    The LLM decides which tool(s) to call and with what arguments.
    Falls back to heuristic dispatch if no API key is available.

    Returns (evidence_items, tool_call_records).
    """
    api_key = os.getenv("OPENAI_API_KEY", "")

    if api_key and api_key != "sk-change-me":
        return _llm_tool_call(step, prior_evidence, api_key)
    else:
        return _fallback_tool_call(step)


def _llm_tool_call(
    step: PlanStep,
    prior_evidence: list[EvidenceItem],
    api_key: str,
) -> tuple[list[EvidenceItem], list[ToolCall]]:
    """Use OpenAI tool-calling to decide which tool to invoke."""
    import json

    from openai import OpenAI

    client = OpenAI(api_key=api_key)

    # Build context from prior evidence (brief summaries only)
    context = ""
    if prior_evidence:
        summaries = [f"- {e.id}: {e.text[:80]}..." for e in prior_evidence[:5]]
        context = "\nEvidence gathered so far:\n" + "\n".join(summaries)

    messages = [
        {
            "role": "system",
            "content": (
                "You are a research assistant investigating a software project. "
                "For the given sub-question, call the most appropriate tool to "
                "find the answer. You have access to a GitHub repository's "
                "issues, PRs, and commits."
            ),
        },
        {
            "role": "user",
            "content": f"Sub-question to investigate: {step.sub_question}{context}",
        },
    ]

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        tools=OPENAI_TOOLS,
        tool_choice="required",
        temperature=0.1,
    )

    all_evidence: list[EvidenceItem] = []
    all_tool_calls: list[ToolCall] = []

    message = response.choices[0].message

    if message.tool_calls:
        for tc in message.tool_calls:
            tool_name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}

            evidence, tool_record = call_tool(tool_name, args)
            all_evidence.extend(evidence)
            all_tool_calls.append(tool_record)

    # If no tool calls were made, fall back
    if not all_tool_calls:
        return _fallback_tool_call(step)

    return all_evidence, all_tool_calls


def _fallback_tool_call(
    step: PlanStep,
) -> tuple[list[EvidenceItem], list[ToolCall]]:
    """Heuristic tool dispatch when no API key is available."""
    hint = (step.tool_hint or "search_issues").lower()

    if hint == "list_pull_requests":
        return call_tool("list_pull_requests", {"state": "all"})
    elif hint == "list_commits":
        return call_tool("list_commits", {"since": ""})
    elif hint == "list_recent_activity":
        return call_tool("list_recent_activity", {"since": "2026-07-01"})
    elif hint == "get_issue":
        return call_tool("search_issues", {"query": step.sub_question[:30]})
    else:
        # Default: search with keywords from the sub-question
        words = step.sub_question.lower().split()
        # Pick meaningful keywords (skip common words)
        stop = {"what", "were", "are", "the", "this", "that", "how", "why",
                "and", "or", "for", "in", "on", "at", "to", "of", "a", "an",
                "is", "was", "has", "have", "been", "any", "which", "did"}
        keywords = [w for w in words if w not in stop][:4]
        query = " ".join(keywords) if keywords else step.sub_question[:30]
        return call_tool("search_issues", {"query": query})
