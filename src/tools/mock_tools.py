"""
Mock tool functions that read from seed_data.json.

Phase 1: hardcoded tool functions returning EvidenceItem lists.
Phase 2: replaced with LLM tool-calling against the same data.
Phase 3: replaced with real MCP tool calls against live GitHub.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from src.tracing.models import EvidenceItem, ToolCall

# ---------------------------------------------------------------------------
# Load seed data once at import time
# ---------------------------------------------------------------------------
_SEED_PATH = Path(__file__).resolve().parent.parent / "data" / "seed_data.json"

with open(_SEED_PATH, encoding="utf-8") as f:
    SEED_DATA: dict[str, Any] = json.load(f)

REPO = SEED_DATA["repo"]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def search_issues(query: str) -> list[EvidenceItem]:
    """
    Keyword-search over seed issues (title, labels, body, comments).

    Returns matching issues as EvidenceItem objects.
    """
    query_lower = query.lower()
    results: list[EvidenceItem] = []

    for issue in SEED_DATA["issues"]:
        searchable = " ".join([
            issue["title"],
            " ".join(issue["labels"]),
            issue["body"],
            " ".join(c["body"] for c in issue["comments"]),
        ]).lower()

        if query_lower in searchable or any(
            label in query_lower for label in issue["labels"]
        ):
            # Build a rich text summary including comments
            comment_text = ""
            if issue["comments"]:
                comment_text = " | Comments: " + " // ".join(
                    f'{c["author"]}: {c["body"]}' for c in issue["comments"]
                )

            results.append(EvidenceItem(
                source="issue",
                id=f"issue-{issue['number']}",
                text=f"[{', '.join(issue['labels'])}] {issue['title']} "
                     f"(state: {issue['state']}): {issue['body']}{comment_text}",
                url=f"https://github.com/{REPO}/issues/{issue['number']}",
                timestamp=issue["created_at"],
            ))

    return results


def list_pull_requests(state: str = "all") -> list[EvidenceItem]:
    """
    List pull requests filtered by state.

    Returns PRs as EvidenceItem objects, including review comments.
    """
    results: list[EvidenceItem] = []

    for pr in SEED_DATA["pull_requests"]:
        if state != "all" and pr["state"] != state:
            continue

        review_text = ""
        if pr["review_comments"]:
            review_text = " | Reviews: " + " // ".join(
                f'{r["author"]}: {r["body"]}' for r in pr["review_comments"]
            )

        closes_text = ""
        if pr.get("closes_issues"):
            closes_text = f" | Closes: #{', #'.join(str(i) for i in pr['closes_issues'])}"

        results.append(EvidenceItem(
            source="pull_request",
            id=f"pr-{pr['number']}",
            text=f"{pr['title']} (state: {pr['state']}): "
                 f"{pr['body']}{closes_text}{review_text}",
            url=f"https://github.com/{REPO}/pull/{pr['number']}",
            timestamp=pr.get("merged_at") or pr["created_at"],
        ))

    return results


def list_commits(since: str = "") -> list[EvidenceItem]:
    """
    List commits, optionally filtered by date.

    Returns commits as EvidenceItem objects.
    """
    results: list[EvidenceItem] = []

    for commit in SEED_DATA["commits"]:
        if since and commit["date"] < since:
            continue

        results.append(EvidenceItem(
            source="commit",
            id=f"commit-{commit['sha']}",
            text=f"{commit['message']} (by {commit['author']})",
            url=f"https://github.com/{REPO}/commit/{commit['sha']}",
            timestamp=commit["date"],
        ))

    return results


# ---------------------------------------------------------------------------
# Tool registry + dispatch with tracing
# ---------------------------------------------------------------------------

TOOL_REGISTRY: dict[str, Any] = {
    "search_issues": search_issues,
    "list_pull_requests": list_pull_requests,
    "list_commits": list_commits,
}


def call_tool(tool_name: str, args: dict[str, Any]) -> tuple[list[EvidenceItem], ToolCall]:
    """
    Call a tool by name with the given args. Returns the evidence items
    and a ToolCall record for the trace.
    """
    func = TOOL_REGISTRY.get(tool_name)
    if func is None:
        return [], ToolCall(
            tool_name=tool_name,
            args=args,
            result=f"Unknown tool: {tool_name}",
            latency_ms=0,
            success=False,
        )

    start = time.perf_counter_ns()
    try:
        evidence = func(**args)
        latency_ms = (time.perf_counter_ns() - start) // 1_000_000
        return evidence, ToolCall(
            tool_name=tool_name,
            args=args,
            result=[e.model_dump() for e in evidence],
            latency_ms=latency_ms,
            success=True,
        )
    except Exception as exc:
        latency_ms = (time.perf_counter_ns() - start) // 1_000_000
        return [], ToolCall(
            tool_name=tool_name,
            args=args,
            result=str(exc),
            latency_ms=latency_ms,
            success=False,
        )
