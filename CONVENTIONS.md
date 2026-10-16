# Conventions — Contributor Notes for This Repo

This file describes what the project is, how the codebase is organized, and the
working conventions to follow. Read it alongside `docs/ROADMAP.md` at the start of
any work session.

## What this project is

An **agentic RAG system over live, changing data** (not a static PDF corpus). It
answers multi-hop questions like:

> "Summarize what changed in Project X this quarter and identify major risks."

by decomposing the question into sub-questions, calling tools (via MCP) against a
live source (GitHub — issues, PRs, comments, commits), pulling in relevant
long-term memory, synthesizing a cited answer, and logging the full trace
(plan → tool calls → evidence → memory used → final answer) for observability.

Full details:
- `docs/PROJECT_BRIEF.md` — what we're building and why, scope boundaries
- `docs/ARCHITECTURE.md` — system design: planner, tool layer, memory, synthesis, tracing
- `docs/ROADMAP.md` — phased build plan, in order, with "definition of done" per phase
- `docs/DEPLOYMENT.md` — how this ships to a public host

**Read `docs/ROADMAP.md` before starting work in a fresh session** and confirm which
phase we're on. Do not jump ahead to later phases even if it seems fast to do so —
each phase has a working, demoable checkpoint and skipping ahead produces an
impressive-looking but untestable pile of code.

## Ground rules

1. **One phase at a time.** Finish and verify a phase (see "Definition of done" in
   ROADMAP.md) before starting the next. After each phase, stop and summarize what
   now works, what's stubbed, and what the next phase will add.
2. **Always keep a working demo path.** At every checkpoint, `make demo` (or
   equivalent) should run end-to-end, even with a mocked data source in early
   phases. Never leave the repo in a state where nothing runs.
3. **Trace everything.** Every run must produce a structured trace object
   (plan, sub-questions, tool calls + args, evidence returned, memory reads/writes,
   final answer + citations). This is the centerpiece of the project — don't treat
   it as an afterthought bolted on at the end.
4. **Memory is selective, not total.** Never implement memory as "store every
   message." Follow the short-term vs. long-term split in `docs/ARCHITECTURE.md`.
   Before writing a memory entry, ask: would this still be useful to recall in two
   weeks? If not, it's short-term/session scope only.
5. **Secrets never get committed.** All API keys / OAuth tokens / MCP server
   credentials go in `.env` (gitignored). Add a `.env.example` with dummy values
   whenever you introduce a new credential.
6. **Prefer small, real integrations over broad, fake ones.** One real MCP
   connector to one real data source (fully working) beats three half-mocked ones.
7. **The data source is GitHub, already decided** (see `docs/PROJECT_BRIEF.md` →
   "Chosen data source"). Don't swap it for a different source without a good
   reason — a repo-scoped PAT and the GitHub tool layer are the whole integration
   surface. Arbitrary per-request repos are validated to `github.com` only.

## Repo layout

```
agentic-rag-project/
├── CONVENTIONS.md             <- this file
├── README.md                  <- human-facing overview
├── docs/
│   ├── PROJECT_BRIEF.md
│   ├── ARCHITECTURE.md
│   ├── ROADMAP.md
│   └── DEPLOYMENT.md
├── src/
│   ├── planner/                <- question decomposition
│   ├── tools/                  <- MCP client + tool wrappers per data source
│   ├── memory/                 <- short-term (session) + long-term (persisted) memory
│   ├── synthesis/              <- final answer generation with citations
│   ├── tracing/                <- trace object + Langfuse (or equivalent) hooks
│   └── api/                    <- FastAPI app exposing /ask
├── frontend/                   <- no-build UI showing plan → tool calls → evidence → answer
├── tests/
├── infra/                      <- Dockerfile, docker-compose, deploy configs
├── .env.example
└── Makefile
```

## Commands

- `make setup` — install deps, copy `.env.example` → `.env`
- `make dev` — run the API + frontend locally
- `make demo` — run a canned multi-hop question end-to-end and print the trace
- `make test` — run the test suite
- `make deploy` — build + deploy (see `docs/DEPLOYMENT.md`)

## Style / conventions

- Python 3.11+, type hints everywhere, `pydantic` models for all tool inputs/outputs
  and for the trace object — this keeps the trace introspectable and demo-ready.
- Keep the planner, tool layer, memory, and synthesis as separate modules with clear
  interfaces — this is what makes the architecture diagram in the README credible
  and lets you swap the data source later without a rewrite.
- Commit in small steps, with messages that map to ROADMAP.md phases
  (e.g. `feat(phase-2): add GitHub tool wrapper + planner decomposition`).
