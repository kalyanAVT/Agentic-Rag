"""
Seed script -- populates a GitHub repo with demo data.

Creates realistic issues, PRs, milestones, and comments on a target
GitHub repo to give the agentic RAG system real data to query.

Usage:
    python scripts/seed_github.py                    # Uses .env defaults
    python scripts/seed_github.py --repo user/repo   # Override repo

Requires: GITHUB_TOKEN env var with Issues:Write and Pull-requests:Write
on the target repo.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta

from dotenv import load_dotenv

load_dotenv()


def get_github_client(repo_name: str):
    """Get authenticated PyGithub client and repo."""
    from github import Github

    token = os.getenv("GITHUB_TOKEN", "")
    if not token or token == "ghp_change-me":
        print("ERROR: Set GITHUB_TOKEN in .env first")
        sys.exit(1)

    gh = Github(token)
    try:
        repo = gh.get_repo(repo_name)
    except Exception as e:
        print(f"ERROR: Cannot access repo '{repo_name}': {e}")
        print("Make sure the repo exists and your PAT has access.")
        sys.exit(1)

    return gh, repo


def create_labels(repo):
    """Ensure required labels exist."""
    desired = {
        "feature": "0e8a16",
        "planning": "1d76db",
        "bug": "d73a4a",
        "blocker": "b60205",
        "customer": "fbca04",
        "enhancement": "a2eeef",
    }
    existing = {l.name for l in repo.get_labels()}

    for name, color in desired.items():
        if name not in existing:
            repo.create_label(name=name, color=color)
            print(f"  Created label: {name}")
        else:
            print(f"  Label exists: {name}")


def create_milestone(repo):
    """Create Q3 milestone if it doesn't exist."""
    for m in repo.get_milestones():
        if "Q3" in m.title:
            print(f"  Milestone exists: {m.title}")
            return m

    due = datetime.now() + timedelta(days=30)
    milestone = repo.create_milestone(
        title="Q3 2026 Release",
        description="Ship data pipeline, dashboard, onboard 3 pilot customers.",
        due_on=due,
    )
    print(f"  Created milestone: {milestone.title}")
    return milestone


def create_issues(repo, milestone):
    """Create demo issues with labels, body, and comments."""
    issues_data = [
        {
            "title": "Define Project X goals and success metrics",
            "body": (
                "We need to define clear goals for Project X this quarter.\n\n"
                "**Proposed goals:**\n"
                "1. Ship the data pipeline (top priority -- all other tasks depend on this)\n"
                "2. Launch the dashboard for internal users\n"
                "3. Onboard 3 pilot customers by end of Q3\n\n"
                "The data pipeline is the critical path -- if it slips, everything slips."
            ),
            "labels": ["feature", "planning"],
            "comments": [
                "Agreed on the priorities. Data pipeline is definitely the blocker for everything else. -- @pm-alice",
                "I can start on the pipeline scaffold this week if we lock the API spec. -- @dev-bob",
            ],
            "close": True,
        },
        {
            "title": "Set up CI/CD pipeline for automated testing",
            "body": (
                "We need GitHub Actions workflows for:\n"
                "- Linting (ruff)\n"
                "- Unit tests (pytest)\n"
                "- Integration tests against staging\n"
                "- Auto-deploy to staging on merge to main"
            ),
            "labels": ["enhancement"],
            "comments": [
                "Using GitHub Actions. Draft PR coming this week.",
            ],
            "close": True,
        },
        {
            "title": "Dashboard not loading for large datasets",
            "body": (
                "**Bug report:**\n\n"
                "When datasets exceed 10,000 rows, the dashboard times out.\n"
                "The frontend is fetching all rows at once via GET /data.\n\n"
                "**Root cause:** No server-side pagination. The API returns the "
                "entire dataset in one response.\n\n"
                "**Impact:** This is blocking pilot customer onboarding -- their "
                "datasets are 50k+ rows.\n\n"
                "**Fix:** Implement cursor-based pagination on the /data endpoint."
            ),
            "labels": ["bug", "blocker"],
            "comments": [
                "This is critical. Moving target date for customer onboarding from Sept 15 to Sept 25. -- @pm-alice",
                "PR #103 (pagination fix) should resolve this. Needs review. -- @dev-carol",
            ],
            "close": False,
        },
        {
            "title": "Pilot customer onboarding delayed",
            "body": (
                "Cannot onboard pilot customers until the dashboard performance "
                "issue (#3) is resolved.\n\n"
                "**Original target:** September 15\n"
                "**New target:** September 25\n\n"
                "If the dashboard fix isn't merged by September 20, we risk "
                "missing the Q3 deadline entirely.\n\n"
                "Customers affected: Acme Corp, Beta Labs, Gamma Inc."
            ),
            "labels": ["blocker", "customer"],
            "comments": [
                "Acme Corp is asking for a timeline update. Need to send them something by Friday. -- @pm-alice",
                "The pagination PR is in review. Should be mergeable by Wednesday. -- @dev-carol",
            ],
            "close": False,
        },
        {
            "title": "Add data export feature for pilot customers",
            "body": (
                "Pilot customers need CSV/JSON export from the dashboard.\n\n"
                "Requirements:\n"
                "- Export filtered view (not entire dataset)\n"
                "- Support CSV and JSON formats\n"
                "- Add download button to dashboard toolbar\n\n"
                "Lower priority than the pagination fix but needed before GA."
            ),
            "labels": ["feature", "customer"],
            "comments": [],
            "close": False,
        },
    ]

    # Check existing issues to avoid duplicates
    existing_titles = {i.title for i in repo.get_issues(state="all")}

    created_issues = []
    for data in issues_data:
        if data["title"] in existing_titles:
            print(f"  Issue exists: {data['title'][:50]}...")
            # Find the existing issue
            for issue in repo.get_issues(state="all"):
                if issue.title == data["title"]:
                    created_issues.append(issue)
                    break
            continue

        issue = repo.create_issue(
            title=data["title"],
            body=data["body"],
            labels=data["labels"],
            milestone=milestone,
        )
        print(f"  Created issue #{issue.number}: {data['title'][:50]}...")

        for comment in data["comments"]:
            issue.create_comment(comment)

        if data["close"]:
            issue.edit(state="closed")

        created_issues.append(issue)

    return created_issues


def seed(repo_name: str):
    """Run the full seed process."""
    print(f"\nSeeding GitHub repo: {repo_name}")
    print("=" * 50)

    gh, repo = get_github_client(repo_name)

    print("\n1. Creating labels...")
    create_labels(repo)

    print("\n2. Creating milestone...")
    milestone = create_milestone(repo)

    print("\n3. Creating issues...")
    issues = create_issues(repo, milestone)

    print(f"\n{'=' * 50}")
    print(f"Done! Created/verified {len(issues)} issues in {repo_name}")
    print(f"View at: https://github.com/{repo_name}/issues")

    gh.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed a GitHub repo with demo data")
    parser.add_argument(
        "--repo",
        default=os.getenv("GITHUB_REPO", ""),
        help="GitHub repo (owner/name). Defaults to GITHUB_REPO from .env",
    )
    args = parser.parse_args()

    if not args.repo:
        print("ERROR: Specify --repo or set GITHUB_REPO in .env")
        sys.exit(1)

    seed(args.repo)
