# Roadmap

Work through these phases **in order**. Each phase ends with a working, demoable
checkpoint. Don't start a phase until the previous one's "Definition of done" is
met. Update the checkboxes as you go so future sessions know where things stand.

## Phase 0 — Scaffolding ✅
- [x] Repo structure created as in `CLAUDE.md`
- [x] `.env.example` with placeholders for: LLM API key, MCP server config,
      LangSmith/Langfuse key
- [x] `Makefile` with `setup`, `dev`, `test` targets (can be stubs for now)
- [x] Minimal FastAPI app with a `/health` endpoint
- **Definition of done:** `make setup && make dev` runs a server that responds
  to `/health`.

## Phase 1 — Hardcoded pipeline (no agent yet) ✅
- Build the *shape* of the system with a fixed, hardcoded plan before adding
  any agentic decision-making — this de-risks the plumbing early.
- [x] Seed a small fake dataset (mock JSON files standing in for GitHub
      issues/PRs/comments for "Project X" — goals, tasks, a changelog,
      some blockers) so Phase 1 doesn't depend on GitHub being wired up yet
- [x] Hardcode a 3-step plan for one canned question
- [x] Hardcoded tool functions that read from the seed data (no MCP yet)
- [x] Synthesis LLM call that takes the evidence and produces a cited answer
- [x] Trace object captured and printed/logged (not yet in LangSmith)
- **Definition of done:** `make demo` runs the one canned question end-to-end
  against fake data and prints plan → evidence → cited answer.

## Phase 2 — Real planner + real tool-calling (still local/mock data) ✅
- [x] Replace the hardcoded plan with an LLM-driven planner (structured output)
- [x] Replace hardcoded tool functions with real LLM tool-calling (the model
      chooses which tool to call, still against the local seed data)
- [x] Trace object grows to include the plan and tool-call args/results
- **Definition of done:** Two different questions against the same seed data
  produce two different, sensible plans and tool-call sequences.

## Phase 3 — Live data source via MCP (GitHub)
- [ ] Create the demo repo (e.g. `demo-project-x`) on GitHub
- [ ] Generate a fine-grained PAT scoped to just that repo; add to `.env`
- [ ] Stand up/connect the official GitHub MCP server, scoped to the demo repo
- [ ] Write `scripts/seed_github.py` to create issues (with labels), a
      milestone with a due date, PRs that close issues, and review/discussion
      comments — real API calls, real timestamps, not hand-typed fixtures
- [ ] Run the seed script; optionally re-run parts of it periodically in the
      days before the demo so activity has a genuine "quarter" of history
- [ ] Swap the mock tool functions from Phase 1/2 for real MCP tool calls
      (`search_issues`, `get_issue`, `list_pull_requests`, `list_commits`,
      plus the custom `list_recent_activity` wrapper)
- [ ] Verify multi-hop questions correctly combine evidence from 2+ tool calls
- **Definition of done:** the 2–3 canned demo questions from
  `docs/PROJECT_BRIEF.md` work correctly against the live `demo-project-x`
  GitHub repo.

## Phase 4 — Memory
- [ ] Implement long-term memory store (SQLite) with the write-back policy
      described in `docs/ARCHITECTURE.md` (atomic facts, not transcripts)
- [ ] Implement memory retrieval feeding into the planner
- [ ] Implement short-term/session memory (in-process)
- [ ] Add at least one demo scenario that proves cross-session recall (e.g.
      state a fact/preference in run 1, confirm it's used unprompted in run 2)
- **Definition of done:** the memory-recall demo question from
  `docs/PROJECT_BRIEF.md` visibly uses a memory entry from a prior session.

## Phase 5 — Observability
- [ ] Wire up LangSmith or Langfuse tracing around planner/tool/synthesis calls
- [ ] Persist the structured `Trace` JSON per run (for the frontend, independent
      of the third-party dashboard)
- **Definition of done:** a run shows up in the LangSmith/Langfuse dashboard
  AND the same run's trace JSON is retrievable from your own API.

## Phase 6 — Frontend
- [ ] Minimal single-page UI: question input + expandable trace sections
      (Plan / Tool Calls / Evidence / Memory Used / Answer with citations)
- [ ] Citations link back to the source (e.g. the GitHub issue/PR/commit)
- **Definition of done:** a non-technical person can ask a question and
  visually follow the whole reasoning chain without reading logs.

## Phase 7 — Deployment
- [ ] Dockerize API + frontend (see `docs/DEPLOYMENT.md`)
- [ ] Deploy to DigitalOcean (App Platform or a droplet — see DEPLOYMENT.md
      for the trade-off)
- [ ] Secrets configured via DO's environment/secrets management, not baked
      into the image
- [ ] Confirm the 2–3 canned demo questions work against the deployed instance
- **Definition of done:** a public URL exists, and the full demo works on it,
  not just locally.

## Phase 8 — Polish for shortlisting
- [ ] README with architecture diagram, live demo link, and a short GIF/video
- [ ] A written "design decisions" section addressing: why this memory
      design, why this planner is linear (not a DAG), what you'd change to
      scale this to production
- [ ] Clean up seed/demo data so the live instance doesn't look empty or fake
- **Definition of done:** you could hand the README + live link to a recruiter
  with zero further explanation needed.
