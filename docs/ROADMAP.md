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

## Phase 4 — Memory ✅
- [x] Implement long-term memory store (SQLite) with the write-back policy
      described in `docs/ARCHITECTURE.md` (atomic facts, not transcripts)
- [x] Implement memory retrieval feeding into the planner (keyword/tag overlap;
      also fed into synthesis so recalled facts are reconciled + cited)
- [x] Implement short-term/session memory (in-process)
- [x] Add at least one demo scenario that proves cross-session recall (e.g.
      state a fact/preference in run 1, confirm it's used unprompted in run 2)
- **Definition of done:** the memory-recall demo question from
  `docs/PROJECT_BRIEF.md` visibly uses a memory entry from a prior session.

## Phase 5 — Observability ✅
- [x] Wire up LangSmith or Langfuse tracing around planner/tool/synthesis calls
      (Langfuse chosen; `src/tracing/observability.py` `emit_trace()` ships one
      trace + planner/tool/synthesis spans per run. Env-gated + graceful no-op
      offline, mirroring `src/llm.py`, so `make demo` needs no key.)
- [x] Persist the structured `Trace` JSON per run (for the frontend, independent
      of the third-party dashboard) — `src/tracing/store.py` writes
      `traces/<ts>-<run_id>.json`; exposed via `GET /runs` + `GET /runs/{run_id}`.
      `POST /ask` runs the pipeline, persists, and returns the Trace.
- **Definition of done:** a run shows up in the LangSmith/Langfuse dashboard
  AND the same run's trace JSON is retrievable from your own API.
  - JSON-half **verified**: `make demo` writes one file per run; the API lists
    and fetches them (see `tests/test_tracing_store.py`, `tests/test_api_runs.py`).
  - Dashboard-half **wired but not lit here** (no Langfuse key in this env): set
    `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY` in `.env` to light it up; the
    hook is a verified no-op until then, so nothing breaks offline.

## Phase 6 — Frontend ✅
- [x] Minimal single-page UI: question input + expandable trace sections
      (Plan / Tool Calls / Evidence / Memory Used / Answer with citations)
      — a no-build static page (`frontend/index.html` + `app.js` + `styles.css`,
      vanilla `fetch`) served by the FastAPI app itself: it POSTs to `/ask`,
      renders the returned `Trace` answer-first, then the reasoning chain, and a
      "recent runs" strip loads past traces via `GET /runs` + `/runs/{run_id}`.
- [x] Citations link back to the source (e.g. the GitHub issue/PR/commit)
      — `[E#]`/`[M#]` markers in the answer become links that open the enclosing
      section, scroll to and flash the matching evidence/memory card; an evidence
      card with a `url` links out to the GitHub issue/PR/commit.
- **Definition of done:** a non-technical person can ask a question and
  visually follow the whole reasoning chain without reading logs.
  - Served on the same app (`app.mount("/", StaticFiles(..., html=True))`,
    mounted last so JSON routes + `/docs` win); `make dev` → open
    <http://localhost:8000/>. Verified offline: page, `app.js`, `styles.css`
    all serve, the JSON API is not shadowed, and stored traces render with
    working citations (see `tests/test_frontend.py`).

## Phase 7 — Deployment 🟡
- [x] Dockerize API + frontend (see `docs/DEPLOYMENT.md`) — one multi-stage,
      non-root image (`infra/Dockerfile`) serving the API + static UI as a single
      Uvicorn process; `infra/docker-compose.yml` for local prod-parity with a
      named volume. `make docker-build` / `docker-run` / `compose-up`.
- [x] Deploy to DigitalOcean (App Platform or a droplet — see DEPLOYMENT.md
      for the trade-off) — App Platform spec written (`infra/do-app.yaml`),
      one-command `make deploy` (`doctl apps create --spec … --upsert`).
      **Live deploy handed off — needs the user's DO account** (`doctl auth init`
      + GitHub repo connected). No Docker daemon / `doctl` on this machine.
- [x] Secrets configured via DO's environment/secrets management, not baked
      into the image — the committed spec carries only offline-safe sentinels
      (`sk-change-me`, …); `.dockerignore` keeps `.env` out of the build context;
      real keys get added Encrypted in the DO dashboard.
- [ ] Confirm the 2–3 canned demo questions work against the deployed instance
      — pending the live deploy above (user-owned hand-off).
- **Definition of done:** a public URL exists, and the full demo works on it,
  not just locally. — *Containerization + deploy config are complete and verified
  statically (`tests/test_deploy_config.py`); the public-URL step is the
  user-owned hand-off (DO account required).*

## Phase 8 — Polish for shortlisting
- [ ] README with architecture diagram, live demo link, and a short GIF/video
- [ ] A written "design decisions" section addressing: why this memory
      design, why this planner is linear (not a DAG), what you'd change to
      scale this to production
- [ ] Clean up seed/demo data so the live instance doesn't look empty or fake
- **Definition of done:** you could hand the README + live link to a recruiter
  with zero further explanation needed.
