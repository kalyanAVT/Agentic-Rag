"""
GitHub tools -- live data access via MCP or REST API.

Phase 3: connects to the GitHub MCP server (Docker stdio) to query
real GitHub repos. Falls back to PyGithub REST API if MCP is unavailable.

Provides the same call_tool() / TOOL_REGISTRY interface as mock_tools.py
so the agent executor works unchanged.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

from src.tracing.models import EvidenceItem, ToolCall

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Sentinel values shipped in .env.example. Their presence means "GitHub is not
# configured yet", so we use mock tools instead of making live API calls.
SENTINEL_REPO = "your-username/demo-project-x"
SENTINEL_TOKEN = "ghp_change-me"


def _get_config() -> dict[str, str]:
    return {
        "token": os.getenv("GITHUB_TOKEN", ""),
        "repo": os.getenv("GITHUB_REPO", ""),
        "mode": os.getenv("GITHUB_MCP_MODE", "docker"),  # docker | remote | rest | none
    }


# ===========================================================================
# MCP-based tool implementations (Docker stdio transport)
# ===========================================================================

async def _mcp_call(tool_name: str, arguments: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Call a tool on the GitHub MCP server via Docker stdio.

    Returns parsed JSON results from the MCP server response.
    """
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    config = _get_config()

    server_params = StdioServerParameters(
        command="docker",
        args=[
            "run", "-i", "--rm",
            "-e", "GITHUB_PERSONAL_ACCESS_TOKEN",
            "ghcr.io/github/github-mcp-server",
        ],
        env={
            "GITHUB_PERSONAL_ACCESS_TOKEN": config["token"],
        },
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            result = await session.call_tool(tool_name, arguments)

            # Parse the result content blocks
            parsed: list[dict[str, Any]] = []
            for content_block in result.content:
                if hasattr(content_block, "text"):
                    try:
                        data = json.loads(content_block.text)
                        if isinstance(data, list):
                            parsed.extend(data)
                        else:
                            parsed.append(data)
                    except json.JSONDecodeError:
                        parsed.append({"text": content_block.text})

            return parsed


def _mcp_call_sync(tool_name: str, arguments: dict[str, Any]) -> list[dict[str, Any]]:
    """Synchronous wrapper around the async MCP call."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Already in an async context -- use a thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, _mcp_call(tool_name, arguments)).result()
    else:
        return asyncio.run(_mcp_call(tool_name, arguments))


# ===========================================================================
# PyGithub REST API fallback
# ===========================================================================

def _get_github_client():
    """Get an authenticated PyGithub client."""
    from github import Github, Auth
    config = _get_config()
    token = config["token"]
    if token and token != SENTINEL_TOKEN:
        return Github(auth=Auth.Token(token)), config["repo"]
    return Github(), config["repo"]


def _rest_search_issues(query: str) -> list[EvidenceItem]:
    """Search issues via GitHub REST API."""
    gh, repo_name = _get_github_client()
    repo = gh.get_repo(repo_name)

    results: list[EvidenceItem] = []
    # Search within the repo
    search_query = f"{query} repo:{repo_name}"
    issues = gh.search_issues(search_query)

    for issue in issues[:10]:  # Cap at 10 results
        labels = ", ".join(l.name for l in issue.labels)
        label_str = f"[{labels}] " if labels else ""
        comments_text = ""
        if issue.comments > 0:
            comments = list(issue.get_comments())[:3]
            comments_text = " | Comments: " + " // ".join(
                f"{c.user.login}: {c.body[:200]}" for c in comments
            )

        results.append(EvidenceItem(
            source="pull_request" if issue.pull_request else "issue",
            id=f"{'pr' if issue.pull_request else 'issue'}-{issue.number}",
            text=f"{label_str}{issue.title} (state: {issue.state}): "
                 f"{(issue.body or '')[:300]}{comments_text}",
            url=issue.html_url,
            timestamp=issue.created_at.isoformat() if issue.created_at else "",
        ))

    gh.close()
    return results


def _rest_get_issue(number: int) -> list[EvidenceItem]:
    """Get a specific issue via GitHub REST API."""
    gh, repo_name = _get_github_client()
    repo = gh.get_repo(repo_name)

    try:
        issue = repo.get_issue(number)
    except Exception:
        gh.close()
        return []

    labels = ", ".join(l.name for l in issue.labels)
    label_str = f"[{labels}] " if labels else ""
    comments_text = ""
    if issue.comments > 0:
        comments = list(issue.get_comments())[:5]
        comments_text = " | Comments: " + " // ".join(
            f"{c.user.login}: {c.body[:200]}" for c in comments
        )

    result = EvidenceItem(
        source="issue",
        id=f"issue-{issue.number}",
        text=f"{label_str}{issue.title} (state: {issue.state}): "
             f"{(issue.body or '')[:500]}{comments_text}",
        url=issue.html_url,
        timestamp=issue.created_at.isoformat() if issue.created_at else "",
    )

    gh.close()
    return [result]


def _rest_list_pull_requests(state: str = "all") -> list[EvidenceItem]:
    """List pull requests via GitHub REST API."""
    gh, repo_name = _get_github_client()
    repo = gh.get_repo(repo_name)

    # Map our state values to GitHub's
    gh_state = "all" if state == "all" else ("closed" if state == "merged" else state)
    results: list[EvidenceItem] = []

    for pr in repo.get_pulls(state=gh_state, sort="updated", direction="desc")[:10]:
        if state == "merged" and not pr.merged:
            continue

        review_text = ""
        try:
            reviews = list(pr.get_reviews())[:3]
            if reviews:
                review_text = " | Reviews: " + " // ".join(
                    f"{r.user.login}: {(r.body or 'Approved')[:200]}" for r in reviews if r.body
                )
        except Exception:
            pass

        results.append(EvidenceItem(
            source="pull_request",
            id=f"pr-{pr.number}",
            text=f"{pr.title} (state: {'merged' if pr.merged else pr.state}): "
                 f"{(pr.body or '')[:300]}{review_text}",
            url=pr.html_url,
            timestamp=(pr.merged_at or pr.created_at).isoformat() if (pr.merged_at or pr.created_at) else "",
        ))

    gh.close()
    return results


def _rest_list_commits(since: str = "") -> list[EvidenceItem]:
    """List commits via GitHub REST API."""
    from datetime import datetime

    gh, repo_name = _get_github_client()
    repo = gh.get_repo(repo_name)

    kwargs: dict[str, Any] = {}
    if since:
        try:
            kwargs["since"] = datetime.fromisoformat(since)
        except ValueError:
            pass

    results: list[EvidenceItem] = []
    for commit in repo.get_commits(**kwargs)[:15]:
        results.append(EvidenceItem(
            source="commit",
            id=f"commit-{commit.sha[:7]}",
            text=f"{commit.commit.message.split(chr(10))[0]} "
                 f"(by {commit.commit.author.name})",
            url=commit.html_url,
            timestamp=commit.commit.author.date.isoformat() if commit.commit.author.date else "",
        ))

    gh.close()
    return results


def _rest_list_recent_activity(since: str = "") -> list[EvidenceItem]:
    """Combined issues + commits since a date via REST API."""
    results: list[EvidenceItem] = []
    results.extend(_rest_search_issues(f"created:>={since}" if since else ""))
    results.extend(_rest_list_commits(since))
    results.sort(key=lambda e: e.timestamp, reverse=True)
    return results


# ===========================================================================
# Unified tool interface (matches mock_tools.py API)
# ===========================================================================

def _make_mcp_tool(mcp_tool_name: str, args_builder):
    """Create a tool function that calls the MCP server."""
    def tool_fn(**kwargs) -> list[EvidenceItem]:
        mcp_args = args_builder(**kwargs)
        config = _get_config()
        mcp_args["repo"] = config["repo"]  # MCP server needs repo context

        try:
            raw_results = _mcp_call_sync(mcp_tool_name, mcp_args)
        except Exception as exc:
            logger.warning(f"MCP call failed for {mcp_tool_name}: {exc}, falling back to REST")
            # Fall back to REST
            rest_fn = REST_TOOLS.get(mcp_tool_name)
            if rest_fn:
                return rest_fn(**kwargs)
            return []

        # Convert MCP results to EvidenceItem
        evidence: list[EvidenceItem] = []
        for item in raw_results:
            evidence.append(EvidenceItem(
                source=item.get("type", "github"),
                id=str(item.get("id", item.get("number", ""))),
                text=json.dumps(item) if isinstance(item, dict) else str(item),
                url=item.get("html_url", item.get("url", "")),
                timestamp=item.get("created_at", item.get("date", "")),
            ))
        return evidence

    tool_fn.__name__ = mcp_tool_name
    tool_fn.__doc__ = f"MCP-backed {mcp_tool_name}"
    return tool_fn


# REST API tool registry (fallback)
REST_TOOLS: dict[str, Any] = {
    "search_issues": _rest_search_issues,
    "get_issue": _rest_get_issue,
    "list_pull_requests": _rest_list_pull_requests,
    "list_commits": _rest_list_commits,
    "list_recent_activity": _rest_list_recent_activity,
}


def _build_tool_registry() -> dict[str, Any]:
    """
    Build the tool registry based on GITHUB_MCP_MODE and credentials.

    Returns an empty registry (-> the agent uses mock tools) unless GitHub is
    actually configured with BOTH a real token and a real repo. This prevents
    accidental unauthenticated live calls against a repo you don't control
    (see CLAUDE.md rule #7).
    """
    config = _get_config()
    mode = config["mode"]
    repo = config["repo"]
    token = config["token"]

    if (
        mode == "none"
        or not repo
        or repo == SENTINEL_REPO
        or not token
        or token == SENTINEL_TOKEN
    ):
        logger.info(
            "GitHub not configured (sentinel/missing token or repo) -- using mock tools."
        )
        return {}

    if mode in ("docker", "remote"):
        # TODO(phase-3): wire the real GitHub MCP client (see _make_mcp_tool /
        # _mcp_call below). Until that lands, live access uses the PyGithub
        # REST API -- functionally equivalent for our read-only tools.
        logger.info(
            "GITHUB_MCP_MODE=%s: MCP transport not yet wired -- using PyGithub "
            "REST API for live GitHub access.",
            mode,
        )
        return REST_TOOLS

    # mode == "rest" (or any other value): live REST API directly.
    logger.info("GitHub tools: live REST API mode.")
    return REST_TOOLS


# The registry the agent uses -- same shape as mock_tools.TOOL_REGISTRY
TOOL_REGISTRY: dict[str, Any] = _build_tool_registry()


def call_tool(tool_name: str, args: dict[str, Any]) -> tuple[list[EvidenceItem], ToolCall]:
    """
    Call a GitHub tool by name. Same interface as mock_tools.call_tool().
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
        logger.error(f"Tool {tool_name} failed: {exc}")
        return [], ToolCall(
            tool_name=tool_name,
            args=args,
            result=str(exc),
            latency_ms=latency_ms,
            success=False,
        )
