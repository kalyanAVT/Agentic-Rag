"""
Seed prior-session memory for the cross-session recall demo.

These entries stand in for durable facts a PRIOR session already captured about
`demo-project-x`. `make demo` seeds them (idempotently) so the recall question
retrieves real memory with no API key -- proving retrieval works offline, while
live write-back (with a key) appends new facts on top. See ARCHITECTURE.md
section 3 and the Phase 4 definition of done in docs/ROADMAP.md.

The facts are grounded in src/data/seed_data.json so the recall answer lines up
with the live evidence the tools return.
"""

from __future__ import annotations

from src.memory.store import MemoryStore
from src.tracing.models import MemoryEntry

# Facts / preferences a prior session captured -- atomic, one fact per entry.
PRIOR_SESSION_FACTS: list[MemoryEntry] = [
    MemoryEntry(
        id="seed-pagination-priority",
        text=(
            "The team decided the dashboard pagination fix (PR #103) is the highest-priority "
            "item and must merge before Sept 20 to hit the Q3 deadline."
        ),
        topic_tags=["pagination", "dashboard", "pr-103", "deadline", "priority"],
        created_at="2026-09-15T09:00:00+00:00",
        source_run_id="seed-prior-session",
    ),
    MemoryEntry(
        id="seed-pilot-deadline",
        text=(
            "Pilot customer onboarding was rescheduled from Sept 15 to Sept 25 because it is "
            "blocked by the dashboard performance issue (#3)."
        ),
        topic_tags=["pilot", "onboarding", "deadline", "blocker", "dashboard"],
        created_at="2026-09-15T09:05:00+00:00",
        source_run_id="seed-prior-session",
    ),
    MemoryEntry(
        id="seed-user-preference",
        text="The user cares most about deadline slippage and blockers, not new feature velocity.",
        topic_tags=["preference", "deadline", "blocker", "priority"],
        created_at="2026-09-15T09:10:00+00:00",
        source_run_id="seed-prior-session",
    ),
]


def seed_prior_session(store: MemoryStore) -> int:
    """Insert the prior-session facts if absent. Idempotent. Returns # inserted."""
    inserted = 0
    for entry in PRIOR_SESSION_FACTS:
        if store.add(entry):
            inserted += 1
    return inserted
