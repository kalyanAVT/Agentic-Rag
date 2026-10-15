"""
Per-request GitHub context (repo + optional token).

A visitor can point a single request at any repo, with an optional token for
private repos. Rather than thread two more parameters through every tool
signature, the pipeline sets an ambient context for the duration of the run and
the tool layer reads it.

ContextVar (not a module global) so concurrent requests -- FastAPI runs sync
endpoints in a thread pool -- stay isolated from each other.

SECURITY: the token lives only here and in the GitHub client built from it. It
is never written to the Trace, to evidence, to tool args/results, to Langfuse,
or to SQLite. Anything that reads the token must keep it out of those sinks.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

# (repo "owner/name", token or None) for the request currently executing; None
# outside a per-request run, in which case the tool layer falls back to env.
_ctx: ContextVar[tuple[str, str | None] | None] = ContextVar(
    "github_request_context", default=None
)


@contextmanager
def github_context(repo: str, token: str | None):
    """Scope the GitHub repo/token to the current request. Resets on exit so a
    worker thread never leaks one request's context into the next."""
    reset = _ctx.set((repo, token))
    try:
        yield
    finally:
        _ctx.reset(reset)


def current_repo() -> str | None:
    """The repo for the current request, or None (=> use env / mock tools)."""
    ctx = _ctx.get()
    return ctx[0] if ctx else None


def current_token() -> str | None:
    """The visitor-supplied token for the current request, or None."""
    ctx = _ctx.get()
    return ctx[1] if ctx else None
