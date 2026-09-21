# Project Brief

## One-line pitch

An agentic RAG assistant that answers multi-hop questions over a live, constantly
changing workspace (GitHub — issues, PRs, commits), using query decomposition, tool-calling via
MCP, short- and long-term memory, and a fully traced plan → evidence → answer
pipeline — deployed as a live demo on DigitalOcean.

## Why this project (for shortlisting / resume)

This is a deliberately chosen project because it touches nearly every skill that
shows up in "agentic AI engineer" and "applied AI" job descriptions in one coherent
system, not five disconnected toy scripts:

| Skill area | Where it shows up here |
|---|---|
| Retrieval / RAG | Retrieval over a live source instead of a static corpus |
| Agentic planning | Query decomposition into sub-questions before retrieval |
| Tool use | MCP-based tool calls against a real external service |
| Memory systems | Explicit short-term vs. long-term memory design (not "store everything") |
| Multi-hop reasoning | Answers require combining evidence from multiple tool calls |
| Observability | Full trace of plan → tool calls → evidence → memory → answer |
| Systems / deployment | Containerized, deployed to a cloud VM, has a real public URL |
| Product sense | A defensible, narrow scope with a clear demo script, not scope creep |

The goal is a system you can **demo live in an interview in under 2 minutes**:
type a multi-hop question, watch the trace unfold (plan, tool calls, evidence,
memory used), and get a cited answer.

## Scope decisions (lock these in before coding)

Fill these in and keep this file updated — Claude Code should treat this section
as the source of truth for scope, and check it at the start of any session.

- **Chosen data source: GitHub** (issues, pull requests, comments, commits on
  one repo you own). Rationale:
  - You almost certainly already have a GitHub account — no new signup, and
    it's genuinely *live* data if you (or, ideally, an ongoing seed script)
    keep opening issues/PRs/comments over the run-up to the demo, rather than
    a one-time fake dataset that goes stale.
  - An official GitHub MCP server exists, so the MCP-connector plumbing is
    mostly "wire it up," and your build time goes into the planner/memory/
    tracing logic instead of writing a REST wrapper from scratch.
  - Maps naturally onto the "Project X" framing: issues = tasks, milestones =
    deadlines, PR merges = changes shipped, review comments/discussion = risks
    and blockers.
  - Repo choice: use one of your own repos (a real side project, or one
    created specifically for this demo). Do **not** point this at someone
    else's repo you don't control — you need to be able to shape what
    "changed this quarter" looks like for the demo to land reliably.
- **Seeding the demo repo:** create a repo (e.g. `demo-project-x`) and, over
  the days/weeks before the interview, script or manually create:
  - a handful of issues with labels (`bug`, `blocker`, `feature`) and a
    milestone with a due date
  - a couple of due-date changes on the milestone (this is your "deadlines
    changed" evidence)
  - PRs that close some issues, with review comments mentioning blockers or
    trade-offs (this is your "risks" evidence)
  - This can be done with a small `scripts/seed_github.py` using the GitHub
    REST API (`PyGithub` or raw `requests`) — treat it as part of Phase 3 in
    `docs/ROADMAP.md`, not a one-off manual chore.
- **MCP server:** use the official GitHub MCP server
  (https://github.com/github/github-mcp-server). Enable/scope it to the demo
  repo only (fine-grained PAT scoped to that repo) rather than your whole
  account. Tool surface you'll actually use (subset of what the server
  exposes): `search_issues`, `get_issue` (incl. comments), `list_pull_requests`,
  `get_pull_request` (incl. review comments), `list_commits`. If the official
  server doesn't expose a clean "recent activity in date range" query, add a
  thin wrapper tool in `src/tools/` that calls `search_issues`/`list_commits`
  with a date filter — no need to write a custom MCP server from scratch.
- **Memory backing store:** start with a local SQLite / file-based store for
  memory (durable across restarts, zero infra cost); note in ARCHITECTURE.md
  where you'd swap in Postgres + pgvector if you wanted to scale this for real.
- **Observability:** LangSmith (or Langfuse as a free/open-source alternative) for
  trace capture, plus a custom trace object stored alongside each answer so the
  frontend can render it without hitting a third-party dashboard.
- **Out of scope for v1** (say so explicitly, so nobody — including the agent —
  scope-creeps into it):
  - Multi-user auth / multi-tenant workspaces
  - Real-time streaming ingestion (polling on a timer is fine)
  - Multiple simultaneous data sources
  - Fine-tuned or custom models (use an off-the-shelf LLM API)

## The demo question(s)

Pick 2–3 canned questions you will seed data for and demo live. Example
(GitHub version, against the seeded `demo-project-x` repo):

1. "Summarize what changed in Project X this quarter and identify major risks."
   (pulls from merged PRs, closed issues, and blocker-labeled/discussed items)
2. "What deadlines changed for Project X, and why?"
   (pulls from milestone due-date history / issues referencing the deadline)
3. "What did we decide about [topic] last week, and is that still the plan?"
   (tests long-term memory recall across sessions — e.g. a decision captured
   from a PR review comment or issue discussion)

## Success criteria

- [ ] A cold, unseeded visitor can ask a multi-hop question and get a correct,
      cited answer sourced from live data (not hardcoded).
- [ ] The UI shows the decomposition (sub-questions), the tool calls made, the
      evidence retrieved, memory entries used, and the final cited answer.
- [ ] Asking a related question in a later session shows memory being recalled
      (e.g. "as we discussed, Project X is the top priority...").
- [ ] Deployed and reachable at a public URL on DigitalOcean.
- [ ] README has an architecture diagram and a 30-second GIF/video of the demo.
