# Deployment (DigitalOcean)

## Choosing between App Platform and a Droplet

| | DigitalOcean App Platform | Droplet (VM) |
|---|---|---|
| Setup effort | Low — connect repo, it builds from Dockerfile | Medium — you provision, install Docker, set up reverse proxy |
| Cost (small demo) | ~$5–12/mo for a basic app | ~$4–6/mo for smallest droplet |
| Control | Less — managed build/deploy | Full control over the box |
| Good for | Getting a public URL fast, minimal ops | Full control over the runtime and the box |
| Recommendation | **Use this for v1** — fastest path to a public HTTPS URL | Consider migrating later if you want to manage the host yourself |

**App Platform is the pragmatic default**: it gets you a public HTTPS URL
quickly and lets you spend your time on the agent itself, not nginx configs. A
droplet with Docker Compose + Caddy/nginx is the alternative when you want to
own the runtime end to end. `render.yaml` is a third option — the same container
on a free tier, deployed from the Render dashboard with no CLI.

## Containerization

- One `Dockerfile` for the API (FastAPI + Uvicorn), one for the frontend if it's
  a separate service (or serve static frontend files from the same FastAPI app
  to keep this simple — recommended for v1).
- `docker-compose.yml` for local dev parity (API + SQLite volume + optional
  local MCP server process).
- Keep the image slim: multi-stage build, `python:3.11-slim` base.

## Environment / secrets

- Never commit `.env`. Commit `.env.example` with every key name and a dummy
  value.
- On App Platform: set env vars/secrets in the app's Settings → App-Level
  Environment Variables (mark API keys as "Encrypted").
- On a Droplet: use a `.env` file with restricted permissions
  (`chmod 600`) loaded by Docker Compose's `env_file:`, or a secrets manager.
- In the web UI, visitors can supply their own keys from the Settings panel;
  those live only in the visitor's browser and are never written server-side
  (see the README's "Bring your own keys").

## Persistent memory storage in production

- SQLite is fine for a single-instance demo, but on App Platform the
  filesystem is ephemeral across deploys/restarts unless you attach a
  volume. Options, in order of effort:
  1. Simplest: accept that memory resets on redeploy for the demo (fine, and
     honestly worth noting as a known limitation in the README).
  2. Attach a DO volume / use App Platform's persistent storage for the
     SQLite file.
  3. Swap to DO's Managed Postgres (has a free/dev tier) — also the path to
     pgvector for real memory search, as noted in `docs/ARCHITECTURE.md`.

## Suggested deploy flow (App Platform)

1. Push repo to GitHub.
2. In DO: Create App → connect repo → it detects the Dockerfile.
3. Set env vars (LLM API key, MCP config, LangSmith/Langfuse key).
4. Attach a volume (or Managed Postgres) if you want memory to survive
   redeploys.
5. Deploy; confirm `/health` responds; run the canned demo questions against
   the public URL before calling this phase done.

## Suggested deploy flow (Droplet)

1. Provision a small droplet (Ubuntu LTS).
2. Install Docker + Docker Compose.
3. Copy repo, set up `.env`, `docker-compose up -d`.
4. Put Caddy (auto-HTTPS, minimal config) or nginx + certbot in front for TLS
   on a real domain/subdomain.
5. Set up a simple systemd unit or Compose restart policy so it survives
   reboots.

## Post-deploy checklist

- [ ] Public URL loads over HTTPS
- [ ] Seed data (`demo-project-x` GitHub repo) is populated and not stale
- [ ] The canned questions run correctly against the live deployment
- [ ] Memory-recall works (or is labeled reset-on-redeploy, if you chose
      option 1 above)
- [ ] Langfuse trace links (if shown) actually resolve
