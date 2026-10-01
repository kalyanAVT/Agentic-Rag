# docs/assets — demo capture checklist (Phase 8 hand-off)

This folder holds the README's visual assets. One is still a **hand-off** because it
needs the running system on screen (and, for the public version, the deployed URL):
a short **demo GIF**. Everything else in Phase 8 (architecture diagram, design-
decisions writeup, demo-data cleanup) is already done in the repo.

## What to capture — `demo.gif`

A ~15–25 second screen capture of the **web UI** telling the whole story end-to-end:

1. `make dev`, then open <http://localhost:8000/>.
2. Ask (or click the example chip for) a multi-hop question — the richest is:
   *"Which open issues are blocking the Q3 release, and are there any pull requests
   addressing them?"*
3. Let the trace render **answer-first**, then expand **Plan → Tool Calls →
   Evidence → Memory Used** so the reasoning chain is visible.
4. Click an `[E#]` / `[M#]` citation to show it jump-scroll + flash the matching
   evidence/memory card (this is the "every claim is cited" payoff).
5. Optionally ask the recall question — *"What did we decide about the dashboard
   pagination fix, and is it still on track?"* — to show a prior-session memory
   fact (`[M1]`) being reused unprompted.

Keep it small (aim < 5 MB). Any recorder works — e.g. [ScreenToGif](https://www.screentogif.com/)
(Windows), [Peek] / `ffmpeg` (Linux), or Kap (macOS). Save it here as `demo.gif`.

> Tip: run with a real `LLM_API_KEY` set (OpenRouter free tier is fine) so the GIF
> shows genuine LLM-driven planning and synthesis, not the offline fallback. With no
> key it still works — it just shows the deterministic digest answer.

## Where it plugs in

`README.md` has a `## Live demo` section with a commented-out, ready-to-paste block.
Once `demo.gif` exists (and, for the public link, the DigitalOcean deploy is live),
uncomment and fill:

```markdown
**▶ Live:** https://agentic-rag-xxxxx.ondigitalocean.app

![Demo — plan → tool calls → evidence → cited answer](docs/assets/demo.gif)
```

The live URL comes from the Phase 7 deploy hand-off (`make deploy`, needs a
DigitalOcean account — see the project README's **Deploy** section and
[`DEPLOYMENT.md`](../DEPLOYMENT.md)).
