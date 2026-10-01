# syntax=docker/dockerfile:1
#
# Agentic RAG -- a single image that serves BOTH the JSON API and the static
# frontend from one FastAPI / Uvicorn process (docs/DEPLOYMENT.md: "serve static
# frontend files from the same FastAPI app to keep this simple -- recommended
# for v1"). One image -> one App Platform service -> one thing to deploy.
#
# Build from the REPO ROOT (the build context), pointing at this file:
#   docker build -f infra/Dockerfile -t agentic-rag:latest .
# The root-level .dockerignore keeps the context (and image) slim and secret-free.

# ---- Stage 1: build dependency wheels (keeps the toolchain out of the final image)
FROM python:3.11-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# ---- Stage 2: slim runtime ------------------------------------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    MEMORY_DB_PATH=/data/memory.db \
    TRACE_DIR=/data/traces

# Install deps from the prebuilt wheels only -- no compiler in the final image.
COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
 && rm -rf /wheels requirements.txt

# Non-root user + a writable /data mount point for the SQLite DB and traces.
RUN useradd --create-home --uid 10001 appuser \
 && mkdir -p /data \
 && chown -R appuser:appuser /data
WORKDIR /app

# Application code only (everything else is excluded by .dockerignore).
COPY --chown=appuser:appuser src/ ./src/
COPY --chown=appuser:appuser frontend/ ./frontend/

USER appuser
EXPOSE 8000

# Container health check (compose / local; App Platform uses its own probe from
# infra/do-app.yaml). Hits the app's /health on whatever $PORT is bound.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import os,sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/health',timeout=2).status==200 else 1)"

# App Platform injects $PORT (8080); default to 8000 everywhere else. Bind all
# interfaces so the container is reachable. `exec` -> uvicorn is PID 1 and gets
# SIGTERM for graceful shutdown. No --reload in production.
CMD ["sh", "-c", "exec uvicorn src.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
