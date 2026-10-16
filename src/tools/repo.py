"""
Repository reference parsing + a typed access error.

The UI lets a visitor point the agent at ANY GitHub repo -- given as a full URL
(https://github.com/owner/name) or a bare owner/name slug. normalize_repo()
turns either into a canonical "owner/name", rejecting anything that is not a
github.com repo, so the tool layer never builds an API call against a host we
don't control (mirrors CONVENTIONS.md rule #7 for the arbitrary-repo case).
"""

from __future__ import annotations

import re

# A GitHub owner is alphanumeric + hyphens; a repo name allows letters, digits,
# and . _ - (GitHub's own naming rules are looser, but this rejects junk cleanly).
_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9._-]+$")


class RepoAccessError(Exception):
    """The repo could not be read: not found, private without a valid token, or
    rate-limited. Carries a message safe to show the user (never the token)."""


def normalize_repo(value: str) -> str:
    """Return the canonical ``owner/name`` for a GitHub repo reference.

    Accepts ``owner/name``, ``github.com/owner/name``, and
    ``https://github.com/owner/name`` (with an optional ``www.``, trailing
    slash, ``.git`` suffix, ``#fragment`` or ``?query``). Raises ``ValueError``
    for empty input, non-github.com hosts, or malformed references.
    """
    raw = (value or "").strip()
    if not raw:
        raise ValueError("Empty repository reference.")

    candidate = raw

    # If it looks like a full URL, only github.com is allowed.
    scheme_match = re.match(r"^[a-z][a-z0-9+.\-]*://", raw, re.IGNORECASE)
    if scheme_match:
        rest = raw[scheme_match.end():]
        host = rest.split("/", 1)[0].lower()
        if host not in ("github.com", "www.github.com"):
            raise ValueError(
                f"Only github.com repositories are supported (got host '{host}')."
            )
        candidate = rest[len(rest.split("/", 1)[0]):]

    # Strip the "github.com/" host prefix for host-without-scheme forms.
    else:
        for host in ("github.com/", "www.github.com/"):
            if candidate.lower().startswith(host):
                candidate = candidate[len(host):]
                break

    # Drop any query / fragment, then a trailing slash and a ".git" suffix.
    candidate = candidate.split("#", 1)[0].split("?", 1)[0]
    candidate = candidate.strip()
    if candidate.endswith("/"):
        candidate = candidate[:-1]
    if candidate.endswith(".git"):
        candidate = candidate[:-4]

    parts = [p for p in candidate.split("/") if p]
    if len(parts) != 2 or not _SLUG_RE.match("/".join(parts)):
        raise ValueError(
            "Could not parse a GitHub repository from that input. "
            "Expected 'owner/name' or 'https://github.com/owner/name'."
        )
    return f"{parts[0]}/{parts[1]}"
