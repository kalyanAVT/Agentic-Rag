# Agentic RAG over Live Data & Memory

> Status: **planning stage** — this repo currently holds the spec/architecture/
> roadmap docs for Claude Code to build from. See `CLAUDE.md` for agent
> instructions.

An agent that answers multi-hop questions over a live, changing GitHub repo
(e.g. "Summarize what changed in Project X this quarter and identify major
risks") by decomposing the question, calling tools against issues/PRs/commits
via the GitHub MCP server, using short- and long-term memory, and producing a
cited answer — with a full trace of plan → tool calls → evidence → memory →
answer.

## Start here

1. `docs/PROJECT_BRIEF.md` — what this is, why, and scope decisions
2. `docs/ARCHITECTURE.md` — system design (planner, tools/MCP, memory, tracing)
3. `docs/ROADMAP.md` — the phased build plan, in order
4. `docs/DEPLOYMENT.md` — shipping this to DigitalOcean
5. `CLAUDE.md` — instructions for Claude Code when working in this repo

## Getting started with Claude Code

```bash
cd agentic-rag-project
claude
```

Then, inside the session, something like:

> Read CLAUDE.md and docs/ROADMAP.md. Let's start Phase 0.

Claude Code will scaffold the repo and work through the roadmap phase by
phase, stopping at each checkpoint for you to review before continuing.

## Live demo

_(fill in once deployed)_ — public URL: TBD

## License

MIT (or your choice)
