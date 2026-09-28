"""
Tests for Phase 4 memory: long-term store, session memory, write-back policy,
seeding, and the offline cross-session recall pipeline (the Phase 4 DoD).
"""

from __future__ import annotations

import pytest

from src.memory.seed import PRIOR_SESSION_FACTS, seed_prior_session
from src.memory.session import SessionMemory
from src.memory.store import MemoryStore
from src.memory.writeback import MemoryCandidate, extract_memories, should_persist
from src.tracing.models import EvidenceItem, MemoryEntry


@pytest.fixture
def store(tmp_path):
    s = MemoryStore(str(tmp_path / "mem.db"))
    yield s
    s.close()


# -- MemoryStore: retrieval ------------------------------------------------

def test_add_and_retrieve_by_keyword(store):
    entry = MemoryEntry(
        id="m1",
        text="The pagination fix PR #103 must merge before Sept 20.",
        topic_tags=["pagination", "pr-103", "deadline"],
    )
    assert store.add(entry) is True

    hits = store.retrieve("what about the pagination fix status")
    assert [h.id for h in hits] == ["m1"]


def test_retrieve_excludes_irrelevant(store):
    store.add(MemoryEntry(id="m1", text="Pagination fix is the top priority.", topic_tags=["pagination"]))
    # Zero token overlap -> not returned (we feed the planner only what's relevant).
    assert store.retrieve("reinforcement learning algorithms") == []


def test_retrieve_respects_top_k(store):
    store.add(MemoryEntry(id="m1", text="Pagination fix is top priority.", topic_tags=["pagination"]))
    store.add(MemoryEntry(id="m2", text="Onboarding deadline moved to September.", topic_tags=["onboarding", "deadline"]))
    store.add(MemoryEntry(id="m3", text="OAuth tokens need rotation before production.", topic_tags=["oauth", "security"]))

    hits = store.retrieve("pagination onboarding oauth deadline", k=2)
    assert len(hits) == 2


# -- MemoryStore: dedup + cap ----------------------------------------------

def test_add_skips_near_duplicate(store):
    a = MemoryEntry(id="a", text="The dashboard pagination fix is the top priority.", topic_tags=["pagination", "priority"])
    b = MemoryEntry(id="b", text="Top priority is the dashboard pagination fix.", topic_tags=["pagination", "priority"])
    assert store.add(a) is True
    assert store.add(b) is False  # same token set -> near-duplicate
    assert store.count() == 1


def test_cap_evicts_oldest(store, monkeypatch):
    import src.memory.store as store_mod
    monkeypatch.setattr(store_mod, "MAX_ENTRIES", 2)

    store.add(MemoryEntry(id="old", text="alpha unique topic one", created_at="2026-01-01T00:00:00+00:00"))
    store.add(MemoryEntry(id="mid", text="bravo unique topic two", created_at="2026-02-01T00:00:00+00:00"))
    store.add(MemoryEntry(id="new", text="charlie unique topic three", created_at="2026-03-01T00:00:00+00:00"))

    ids = {e.id for e in store.all()}
    assert store.count() == 2
    assert ids == {"mid", "new"}  # oldest evicted


# -- Seeding ----------------------------------------------------------------

def test_seed_is_idempotent(store):
    first = seed_prior_session(store)
    assert first == len(PRIOR_SESSION_FACTS)
    assert store.count() == len(PRIOR_SESSION_FACTS)

    second = seed_prior_session(store)
    assert second == 0  # already present -> nothing new
    assert store.count() == len(PRIOR_SESSION_FACTS)


# -- Write-back policy ------------------------------------------------------

def test_should_persist_filters_candidates():
    good = MemoryCandidate(text="Pagination fix PR #103 must merge before Sept 20.", topic_tags=["pagination"])
    too_short = MemoryCandidate(text="ok", topic_tags=[])
    ephemeral = MemoryCandidate(text="No evidence was found for this question.", topic_tags=[])

    assert should_persist(good) is True
    assert should_persist(too_short) is False
    assert should_persist(ephemeral) is False


def test_extract_memories_offline_is_noop(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-change-me")
    assert extract_memories("q", "a", [], "run1") == []


# -- SessionMemory ----------------------------------------------------------

def test_session_memory_dedups_evidence():
    sm = SessionMemory()
    e1 = EvidenceItem(source="issue", id="issue-1", text="first")
    e2 = EvidenceItem(source="issue", id="issue-1", text="duplicate id")
    e3 = EvidenceItem(source="pr", id="pr-9", text="second")

    added = sm.add_evidence([e1, e2, e3])
    assert [e.id for e in added] == ["issue-1", "pr-9"]
    assert len(sm.evidence) == 2


# -- Integration: offline cross-session recall (Phase 4 DoD) ---------------

def test_recall_pipeline_offline(tmp_path, monkeypatch):
    """The recall question retrieves a seeded prior-session fact and the
    fallback answer visibly uses it -- with no API key and mock tools."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-change-me")  # force offline everywhere

    import src.agent as agent_mod
    monkeypatch.setattr(agent_mod.github_tools, "TOOL_REGISTRY", {})  # force mock tools

    from src.demo import run_pipeline

    store = MemoryStore(str(tmp_path / "mem.db"))
    seed_prior_session(store)
    trace = run_pipeline(
        "What did we decide about the dashboard pagination fix, and is it still on track?",
        store,
    )
    store.close()

    assert trace.memory_used, "expected prior-session memory to be recalled"
    assert any("pagination" in m.text.lower() for m in trace.memory_used)
    assert "[M1]" in trace.answer  # fallback synthesis cites recalled memory
