# Agentic RAG over Live Data & Memory

An agent that answers **multi-hop questions over a live, changing GitHub repo**
(issues, PRs, commits) — not a static PDF corpus. It decomposes a question into
sub-questions, calls tools to gather evidence, reconciles that against long-term
memory from prior sessions, and produces a **cited answer** — while emitting a
full structured **trace** of every step: `plan → tool calls → evidence → memory → answer`.

> **Status: working MVP (Phases 0–4).** The full pipeline runs end-to-end today.
> It is **provider-agnostic** (OpenAI / OpenRouter / xAI Grok) and, with no API
> key, degrades gracefully to a deterministic **offline path** so `make demo`
> always produces a complete trace. Live GitHub verification, observability
> dashboards, the web UI, and deployment are the remaining phases (see
> [Roadmap status](#roadmap-status)).

## What it does

Ask a multi-hop question like:

> *"What did we decide about the dashboard pagination fix, and is it still on track?"*

and the agent will:

1. **Recall** relevant facts from long-term memory (e.g. a decision captured in a prior session).
2. **Plan** — decompose the question into 2–5 ordered, tool-answerable sub-questions.
3. **Act** — for each sub-question, call the most appropriate tool (`search_issues`, `list_pull_requests`, `list_commits`, …) against the GitHub data source.
4. **Synthesize** a structured answer that cites every claim (`[E1]`, `[E2]`, …) and reconciles recalled memory (`[M1]`) against the current evidence.
5. **Write back** any durable new facts worth remembering in future sessions (selective, not "store everything").
6. **Trace** the whole run as an introspectable object (plan, tool-call args/results, evidence, memory read/written, citations, timings).

## Architecture

```
                        ┌──────────────┐
   question ──────────▶ │  long-term   │  recall relevant facts
                        │   memory     │  (SQLite, keyword/tag overlap)
                        └──────┬───────┘
                               ▼
                        ┌──────────────┐
                        │   PLANNER    │  LLM structured output → 2–5 sub-questions
                        └──────┬───────┘  (offline: keyword heuristic)
                               ▼
                        ┌──────────────┐   ┌─────────────────────────┐
                        │    AGENT     │──▶│  TOOL LAYER             │
                        │ tool-calling │   │  GitHub REST (live) or  │
                        └──────┬───────┘   │  mock seed data (offline)│
                               │           └─────────────────────────┘
                               ▼  evidence (deduped in session memory)
                        ┌──────────────┐
                        │  SYNTHESIS   │  cited answer ([E1], [M1], …)
                        └──────┬───────┘  (offline: honest evidence digest)
                               ▼
                        ┌──────────────┐
                        │  WRITE-BACK  │  persist durable new facts
                        └──────┬───────┘
                               ▼
                     structured Trace object
              (plan · tool calls · evidence · memory · citations · timing)
```

Each stage is a separate module with a clear interface, so the data source or LLM
provider can be swapped without a rewrite. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

| Module | Path | Responsibility |
|---|---|---|
| Planner | [`src/planner/`](src/planner/) | Question → ordered sub-questions (LLM structured output + heuristic fallback) |
| Tool layer | [`src/tools/`](src/tools/) | GitHub REST wrappers + mock seed tools, uniform `call_tool` interface |
| Agent | [`src/agent.py`](src/agent.py) | LLM tool-calling loop per sub-question |
| Memory | [`src/memory/`](src/memory/) | Long-term store (SQLite) + session memory + selective write-back |
| Synthesis | [`src/synthesis/`](src/synthesis/) | Cited answer generation, memory reconciliation |
| Tracing | [`src/tracing/`](src/tracing/) | Pydantic `Trace` model — the introspectable centerpiece |
| LLM config | [`src/llm.py`](src/llm.py) | Provider-agnostic client (OpenAI / OpenRouter / Grok) |
| API | [`src/api/`](src/api/) | FastAPI app (`/health`) |

## Quickstart

Requires **Python 3.11+**.

```bash
# 1. Install deps and create .env from the template
make setup

# 2. Run the end-to-end demo (3 multi-hop questions, full trace printed)
make demo

# 3. Run the test suite
make test
```

> On Windows without `make`, call the venv Python directly, e.g.
> `.venv/Scripts/python.exe -m src.demo` and `.venv/Scripts/python.exe -m pytest tests/ -q`.

`make demo` works **with no API key** — it runs the deterministic offline path and
still prints a complete plan → evidence → cited answer → trace for all three
questions, including a cross-session memory-recall scenario. Set a real LLM key
(below) for genuine LLM-driven planning, tool-calling, and analytical synthesis.

## LLM provider configuration

The pipeline talks to its LLM through the OpenAI SDK, which speaks to **any
OpenAI-compatible provider** — so switching providers is pure `.env` config, no
code change. Configure it in `.env` (see [`.env.example`](.env.example)):

| Variable | Purpose |
|---|---|
| `LLM_API_KEY` | Provider API key. Overrides `OPENAI_API_KEY` if set. |
| `LLM_BASE_URL` | OpenAI-compatible endpoint. Leave unset for OpenAI. |
| `LLM_MODEL` | Model id (default `gpt-4o-mini`). |

**OpenAI** (default) — just set `OPENAI_API_KEY`.

**OpenRouter** (has a genuinely free tier):

```dotenv
LLM_API_KEY=sk-or-v1-your-key
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=google/gemini-2.0-flash-exp:free
```

**xAI Grok:**

```dotenv
LLM_API_KEY=xai-your-key
LLM_BASE_URL=https://api.x.ai/v1
LLM_MODEL=grok-2-latest
```

> The planner (structured output) and agent (tool-calling) need a model that
> supports those features — `google/gemini-2.0-flash-exp:free` and the Grok
> models do. If a chosen model lacks them, those stages fall back to the
> deterministic path automatically; the demo never crashes. Every LLM call site
> is wrapped so any auth/rate-limit/network error degrades to the offline path
> (locked in by [`tests/test_resilience.py`](tests/test_resilience.py)).

## Data source

The data source is **GitHub** (issues, PRs, comments, commits on a repo you own),
accessed via a repo-scoped fine-grained PAT. `GITHUB_MCP_MODE` in `.env` selects
the access mode; with the sentinel values it runs entirely on **mock seed data**,
so the demo is fully self-contained offline. Point `GITHUB_REPO` only at a repo
you control. See [`docs/PROJECT_BRIEF.md`](docs/PROJECT_BRIEF.md) for the rationale.

## Repo layout

```
agentic-rag-project/
├── docs/            PROJECT_BRIEF · ARCHITECTURE · ROADMAP · DEPLOYMENT
├── src/
│   ├── planner/     question decomposition
│   ├── tools/       GitHub REST + mock tool wrappers
│   ├── memory/      long-term (SQLite) + session memory + write-back
│   ├── synthesis/   cited answer generation
│   ├── tracing/     Trace pydantic models
│   ├── api/         FastAPI app (/health)
│   ├── agent.py     LLM tool-calling loop
│   ├── llm.py       provider-agnostic LLM client
│   └── demo.py      end-to-end runner
├── scripts/         seed helpers
├── tests/           pytest suite
├── .env.example     all env vars documented
└── Makefile         setup · dev · demo · test · seed-memory
```

## Roadmap status

Full detail (with "definition of done" per phase) in [`docs/ROADMAP.md`](docs/ROADMAP.md).

| Phase | Scope | Status |
|---|---|---|
| 0 | Scaffolding, FastAPI `/health`, Makefile | ✅ Done |
| 1 | Hardcoded pipeline over seed data + synthesis + trace | ✅ Done |
| 2 | LLM-driven planner + real tool-calling | ✅ Done |
| 3 | Live GitHub data source | 🟡 REST tool layer built; live verification deferred (mock fallback works) |
| 4 | Long-term + session memory, selective write-back, cross-session recall | ✅ Done |
| 5 | Observability (LangSmith/Langfuse + persisted Trace JSON) | ⬜ Next |
| 6 | Minimal web UI (question → expandable trace) | ⬜ Planned |
| 7 | Dockerize + deploy to DigitalOcean | ⬜ Planned |
| 8 | Polish (architecture diagram, demo GIF, design-decisions writeup) | ⬜ Planned |

## Design decisions

- **Linear plan, not a DAG.** Each sub-question is independently answerable, which
  keeps the trace legible and the executor simple. A DAG would buy parallelism at
  the cost of demo clarity — noted as a future scaling change.
- **Selective memory, not "store everything".** Write-back extracts 0–3 *atomic,
  durable* facts per exchange ("would this still be useful in two weeks?") and
  dedups before insert — transcripts are never stored.
- **Always a working demo path.** Every LLM call site has a deterministic offline
  fallback, so the system is demoable with zero credentials and never left in a
  broken state.
- **SQLite for memory** (durable, zero-infra); the interface leaves room to swap
  in Postgres + pgvector to scale.

## License

MIT
