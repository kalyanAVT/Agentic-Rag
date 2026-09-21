"""Tests for mock tool functions."""

from src.tools.mock_tools import (
    call_tool,
    list_commits,
    list_pull_requests,
    search_issues,
)


def test_search_issues_finds_blockers() -> None:
    results = search_issues("blocker")
    assert len(results) >= 2  # issues 3 and 4 have "blocker" label
    ids = {e.id for e in results}
    assert "issue-3" in ids
    assert "issue-4" in ids


def test_search_issues_finds_goals() -> None:
    results = search_issues("goals")
    assert len(results) >= 1
    assert any("issue-1" == e.id for e in results)


def test_list_pull_requests_all() -> None:
    results = list_pull_requests("all")
    assert len(results) == 3  # 3 PRs in seed data


def test_list_pull_requests_merged() -> None:
    results = list_pull_requests("merged")
    assert len(results) == 2  # PRs 101 and 102


def test_list_commits_all() -> None:
    results = list_commits()
    assert len(results) == 4


def test_list_commits_since_filter() -> None:
    results = list_commits(since="2026-08-01")
    assert len(results) >= 2  # commits from August onward
    assert all(e.timestamp >= "2026-08-01" for e in results)


def test_call_tool_success() -> None:
    evidence, tc = call_tool("search_issues", {"query": "blocker"})
    assert tc.success is True
    assert tc.tool_name == "search_issues"
    assert len(evidence) >= 2


def test_call_tool_unknown() -> None:
    evidence, tc = call_tool("nonexistent_tool", {})
    assert tc.success is False
    assert evidence == []


def test_evidence_has_urls() -> None:
    results = search_issues("blocker")
    for e in results:
        assert e.url.startswith("https://github.com/")
        assert e.source == "issue"
