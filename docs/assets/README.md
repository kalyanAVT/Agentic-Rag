# docs/assets — README visuals

This folder holds the images the README links to. Everything else in the polish
phase (architecture diagram, design-decisions writeup, demo-data cleanup) is
already in the repo; the demo GIF is the last item.

## What to capture — `demo.gif`

A ~15–25 second screen capture of the **web UI** showing the whole flow:

1. Start the app (`make dev`, or `uvicorn src.api.main:app --port 8000`), open
   <http://localhost:8000/>.
2. Ask (or click the example chip for) a multi-hop question — the richest is
   *"Which open issues are blocking the Q3 release, and are there any pull requests
   addressing them?"*
3. Let the trace render **answer-first**, then expand **Plan → Tool Calls →
   Evidence → Memory Used** so the reasoning chain is visible.
4. Click an `[E#]` / `[M#]` citation to show it jump-scroll and flash the matching
   evidence/memory card (every claim is cited).
5. Optionally ask the recall question — *"What did we decide about the dashboard
   pagination fix, and is it still on track?"* — to show a prior-session memory
   fact (`[M1]`) being reused unprompted.

Keep it small (aim < 5 MB). Any recorder works — e.g.
[ScreenToGif](https://www.screentogif.com/) (Windows), `ffmpeg` or Peek (Linux),
Kap (macOS). Save it here as `demo.gif`.

> Tip: run with a real `LLM_API_KEY` set (the OpenRouter free tier is fine) so the
> GIF shows genuine LLM-driven planning and synthesis rather than the offline
> fallback. With no key it still works — it just shows the deterministic digest.

## Where it plugs in

The README's `## Live demo` section links the live URL and has a ready-to-fill
image line:

```markdown
![Demo — plan → tool calls → evidence → cited answer](docs/assets/demo.gif)
```

Deployment options and the live URL are covered in the project README's **Deploy**
section and [`DEPLOYMENT.md`](../DEPLOYMENT.md).
