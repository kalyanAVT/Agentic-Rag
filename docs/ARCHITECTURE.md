# Architecture

## High-level flow

```
                         ┌─────────────────────────────────────────┐
                         │              User question                │
                         │  "Summarize what changed in Project X    │
                         │   this quarter and identify risks."       │
                         └───────────────────┬───────────────────────┘
                                              ▼
                         ┌─────────────────────────────────────────┐
                         │  1. PLANNER (query decomposition)         │
                         │  - reads relevant long-term memory first  │
                         │  - breaks question into sub-questions:    │
                         │    a) what were Project X's goals?        │
                         │    b) what tasks were due this quarter?   │
                         │    c) what deadlines changed, and when?   │
                         │    d) what blockers were reported?        │
                         └───────────────────┬───────────────────────┘
                                              ▼
                         ┌─────────────────────────────────────────┐
                         │  2. TOOL LAYER (MCP client)                │
                         │  For each sub-question, agent selects and  │
                         │  calls one or more tools:                  │
                         │   - search(query)                          │
                         │   - list_recent_changes(project, range)    │
                         │   - get_page_content(page_id)               │
                         │  Each call + result is logged to the trace │
                         └───────────────────┬───────────────────────┘
                                              ▼
                         ┌─────────────────────────────────────────┐
                         │  3. EVIDENCE STORE (per-run, ephemeral)    │
                         │  Normalized {source, id, text, url,        │
                         │  timestamp} chunks collected across all    │
                         │  tool calls for this run                   │
                         └───────────────────┬───────────────────────┘
                                              ▼
                         ┌─────────────────────────────────────────┐
                         │  4. SYNTHESIS                              │
                         │  LLM call: sub-questions + evidence +      │
                         │  relevant memory → final answer with       │
                         │  inline citations back to evidence items   │
                         └───────────────────┬───────────────────────┘
                                              ▼
                         ┌─────────────────────────────────────────┐
                         │  5. MEMORY WRITE-BACK                      │
                         │  Decide what's worth persisting long-term  │
                         │  (see "Memory design" below)                │
                         └───────────────────┬───────────────────────┘
                                              ▼
                         ┌─────────────────────────────────────────┐
                         │  6. TRACE OUTPUT                           │
                         │  Full structured trace persisted + shipped │
                         │  to LangSmith/Langfuse + shown in UI        │
                         └─────────────────────────────────────────┘
```

## 1. Planner (query decomposition)

- Single LLM call (structured output, e.g. a Pydantic model
  `PlanStep(question: str, tool_hint: str | None)`), given:
  - the raw user question
  - any relevant long-term memory retrieved for this topic (see below)
  - a short description of available tools
- Output: an ordered list of 2–5 sub-questions. Keep this **linear** for v1
  (no branching/conditional plans) — a DAG planner is a nice v2 extension, not
  a v1 requirement.
- Log the raw plan into the trace immediately, before any tool calls happen —
  this makes partial failures still demoable.

## 2. Tool layer (MCP)

- All external-data access goes through an MCP client talking to the
  **official GitHub MCP server**, scoped to one demo repo (e.g.
  `demo-project-x`) via a fine-grained, repo-scoped PAT. Keep the tool
  surface small and composable — a thin subset of what the server exposes,
  plus one custom wrapper tool where needed:
  - `search_issues(query: str) -> list[Issue]` — issues/PRs matching a query
    or label (e.g. `label:blocker`)
  - `get_issue(number: int) -> IssueDetail` — issue/PR body + comments/reviews
  - `list_pull_requests(state: str) -> list[PullRequest]` — merged/open PRs
  - `list_commits(since: date) -> list[Commit]`
  - `list_recent_activity(since: date) -> list[ChangeEvent]` — **custom
    wrapper** (in `src/tools/`) that combines `search_issues` + `list_commits`
    filtered by date, since the raw MCP server doesn't expose a single
    "what changed since X" call. This is the one place you write source-
    specific glue code; everything else rides on the MCP server as-is.
- The agent (not hardcoded logic) decides, per sub-question, which tool(s) to
  call and with what arguments — this is what makes it "agentic" rather than a
  fixed pipeline. Use your LLM SDK's native tool-calling/function-calling, not
  a hand-rolled regex parser of the model's output.
- Every tool call is wrapped so that (args, raw result, latency, success/error)
  gets appended to the trace, regardless of what else happens.

## 3. Memory design — the part to get right

This is the section most likely to be probed in an interview, so be precise
about the split:

### Short-term (session) memory
- Scope: a single conversation/run.
- Contents: the sub-questions asked so far, evidence already retrieved, partial
  synthesis — i.e. working memory needed to answer *this* question without
  re-fetching things it just fetched.
- Storage: in-process (a plain object/dict), never persisted beyond the run.

### Long-term (cross-session) memory
- Scope: persists across sessions/days.
- Contents: **facts and preferences, not transcripts.** E.g.:
  - "Project X is currently the company's top priority" (stated fact/preference)
  - "The user cares most about deadline slippage and blockers, not headcount"
    (inferred preference from repeated question patterns)
  - NOT: full message logs, NOT every retrieved chunk, NOT raw tool outputs.
- Write-back policy (implement this explicitly as a function, e.g.
  `should_persist(candidate: MemoryCandidate) -> bool`):
  1. After synthesis, run a small LLM judgment step: "Is there a durable fact
     or preference in this exchange worth remembering for future sessions?"
  2. If yes, write a short, atomic memory entry (one fact per entry) with a
     timestamp and source reference, not a dump of the conversation.
  3. Cap total memory size / dedupe against existing entries (e.g. embedding
     similarity check before insert) — don't let it grow unboundedly.
- Retrieval: when the planner runs, do a lightweight semantic/keyword lookup
  against long-term memory for entries relevant to the current question's
  topic, and feed only those (not the whole memory store) into the planner
  prompt.
- Storage: SQLite table (or a small vector store, e.g. `chromadb`/`sqlite-vss`)
  with columns like `id, text, topic_tags, created_at, source_run_id`. This is
  intentionally simple — the point to demonstrate is the *policy* (what goes in,
  what doesn't), not a fancy vector DB.

## 4. Synthesis

- One LLM call: sub-questions + their answers/evidence + relevant memory →
  final answer.
- Require inline citations mapping claims to evidence item IDs
  (e.g. `[E3]`), and render these as clickable links back to the source in the
  UI (e.g. back to the GitHub issue, PR, or commit).
- If evidence is insufficient to answer part of the question, the answer
  should say so explicitly rather than hallucinating — worth calling out
  in the demo as a deliberate design choice.

## 5. Tracing / observability

- Define one `Trace` pydantic model that captures the entire run:
  ```python
  class Trace(BaseModel):
      run_id: str
      question: str
      memory_used: list[MemoryEntry]
      plan: list[PlanStep]
      tool_calls: list[ToolCall]   # args, result, latency, success
      evidence: list[EvidenceItem]
      memory_written: list[MemoryEntry]
      answer: str
      citations: list[Citation]
      timing_ms: dict[str, int]
  ```
- Ship this to LangSmith (or Langfuse) via their SDK for the "real" trace/debug
  view, AND persist it (e.g. as JSON per run) so the frontend can render its
  own step-by-step visualization without depending on a third-party dashboard
  being reachable during a live demo.

## 6. Frontend (minimal)

- Single page: input box, "Ask" button, and a results panel with expandable
  sections: **Plan → Tool Calls → Evidence → Memory Used → Answer (cited)**.
- This can be a simple React/HTML page hitting a FastAPI `/ask` endpoint that
  returns the `Trace` object as JSON — no need for a heavy framework.

## Extension points (mention in README, don't build for v1)

- Swap SQLite memory store for Postgres + pgvector for real scale.
- DAG-based planner with conditional/branching sub-questions.
- Multiple data sources fused in one answer.
- Streaming ingestion instead of polling.
