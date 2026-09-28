"""
Mock tool functions that read from seed_data.json.

Phase 1: hardcoded tool functions returning EvidenceItem lists.
Phase 2: replaced with LLM tool-calling against the same data.
Phase 3: replaced with real MCP tool calls against live GitHub.
"""

from __future__ import annotations

import json
import re
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

# Function words + generic glue that shouldn't drive a keyword search. Keeping
# these out stops multi-word queries (e.g. a memory-reconcile sub-question) from
# matching every issue on a stopword like "and"/"status".
_SEARCH_STOPWORDS = {
    "and", "the", "for", "was", "are", "were", "has", "have", "been", "did",
    "does", "any", "all", "about", "which", "what", "when", "where", "why",
    "how", "this", "that", "with", "from", "into", "over", "current", "status",
    "whether", "still", "track", "related", "regarding", "most", "recent",
}


def _keywords(text: str) -> set[str]:
    """Meaningful search tokens: alphanumeric, length >= 3, minus stopwords."""
    return {
        tok
        for tok in re.split(r"[^a-z0-9]+", text.lower())
        if len(tok) >= 3 and tok not in _SEARCH_STOPWORDS
    }


def _issue_evidence(issue: dict[str, Any]) -> EvidenceItem:
    """Build a rich EvidenceItem for an issue, including its comments."""
    comment_text = ""
    if issue["comments"]:
        comment_text = " | Comments: " + " // ".join(
            f'{c["author"]}: {c["body"]}' for c in issue["comments"]
        )
    return EvidenceItem(
        source="issue",
        id=f"issue-{issue['number']}",
        text=f"[{', '.join(issue['labels'])}] {issue['title']} "
             f"(state: {issue['state']}): {issue['body']}{comment_text}",
        url=f"https://github.com/{REPO}/issues/{issue['number']}",
        timestamp=issue["created_at"],
    )


def _pr_evidence(pr: dict[str, Any]) -> EvidenceItem:
    """Build a rich EvidenceItem for a pull request, including reviews."""
    review_text = ""
    if pr["review_comments"]:
        review_text = " | Reviews: " + " // ".join(
            f'{r["author"]}: {r["body"]}' for r in pr["review_comments"]
        )
    closes_text = ""
    if pr.get("closes_issues"):
        closes_text = f" | Closes: #{', #'.join(str(i) for i in pr['closes_issues'])}"
    return EvidenceItem(
        source="pull_request",
        id=f"pr-{pr['number']}",
        text=f"{pr['title']} (state: {pr['state']}): "
             f"{pr['body']}{closes_text}{review_text}",
        url=f"https://github.com/{REPO}/pull/{pr['number']}",
        timestamp=pr.get("merged_at") or pr["created_at"],
    )


def search_issues(query: str) -> list[EvidenceItem]:
    """
    Keyword-search over seed issues AND pull requests (title, labels, body,
    comments/reviews).

    Mirrors GitHub's search API, which returns both issues and PRs and matches
    on token overlap rather than treating the whole query as one phrase. Results
    are ranked by how many query keywords they match (most first), so a
    multi-topic query surfaces its most relevant hits at the top.
    """
    query_lower = query.lower().strip()
    q_keywords = _keywords(query)

    # (score, insertion_order, item) -- insertion_order gives a stable tiebreak
    # (issues before PRs) so equal-score results stay deterministic.
    scored: list[tuple[int, int, EvidenceItem]] = []
    order = 0

    for issue in SEED_DATA["issues"]:
        searchable = " ".join([
            issue["title"],
            " ".join(issue["labels"]),
            issue["body"],
            " ".join(c["body"] for c in issue["comments"]),
        ]).lower()
        overlap = q_keywords & _keywords(searchable)
        label_hit = any(label in query_lower for label in issue["labels"])
        phrase_hit = bool(query_lower) and query_lower in searchable
        if overlap or label_hit or phrase_hit:
            score = len(overlap) + (1 if label_hit else 0) + (1 if phrase_hit else 0)
            scored.append((score, order, _issue_evidence(issue)))
        order += 1

    for pr in SEED_DATA["pull_requests"]:
        searchable = " ".join([
            pr["title"],
            pr["body"],
            " ".join(r["body"] for r in pr["review_comments"]),
        ]).lower()
        overlap = q_keywords & _keywords(searchable)
        phrase_hit = bool(query_lower) and query_lower in searchable
        if overlap or phrase_hit:
            score = len(overlap) + (1 if phrase_hit else 0)
            scored.append((score, order, _pr_evidence(pr)))
        order += 1

    scored.sort(key=lambda t: (-t[0], t[1]))  # score desc, then stable by order
    return [item for _, _, item in scored]


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


def get_issue(number: int) -> list[EvidenceItem]:
    """
    Get full details of a specific issue by number.

    Returns the issue body and all comments as evidence.
    """
    for issue in SEED_DATA["issues"]:
        if issue["number"] == number:
            comment_text = ""
            if issue["comments"]:
                comment_text = " | Comments: " + " // ".join(
                    f'{c["author"]}: {c["body"]}' for c in issue["comments"]
                )

            return [EvidenceItem(
                source="issue",
                id=f"issue-{issue['number']}",
                text=f"[{', '.join(issue['labels'])}] {issue['title']} "
                     f"(state: {issue['state']}): {issue['body']}{comment_text}",
                url=f"https://github.com/{REPO}/issues/{issue['number']}",
                timestamp=issue["created_at"],
            )]

    return []


def list_recent_activity(since: str = "") -> list[EvidenceItem]:
    """
    Combined view of issues + commits since a date.

    Custom wrapper tool per ARCHITECTURE.md -- combines search_issues +
    list_commits filtered by date.
    """
    results: list[EvidenceItem] = []

    # Recent issues
    for issue in SEED_DATA["issues"]:
        if since and issue["created_at"] < since:
            continue
        results.append(EvidenceItem(
            source="issue",
            id=f"issue-{issue['number']}",
            text=f"[{', '.join(issue['labels'])}] {issue['title']} (state: {issue['state']})",
            url=f"https://github.com/{REPO}/issues/{issue['number']}",
            timestamp=issue["created_at"],
        ))

    # Recent commits
    results.extend(list_commits(since=since))

    # Sort by timestamp descending
    results.sort(key=lambda e: e.timestamp, reverse=True)
    return results


# ---------------------------------------------------------------------------
# Tool registry + dispatch with tracing
# ---------------------------------------------------------------------------

TOOL_REGISTRY: dict[str, Any] = {
    "search_issues": search_issues,
    "get_issue": get_issue,
    "list_pull_requests": list_pull_requests,
    "list_commits": list_commits,
    "list_recent_activity": list_recent_activity,
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
