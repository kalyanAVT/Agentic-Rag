"""
Long-term memory write-back policy.

After synthesis, decide what (if anything) from this exchange is a durable FACT
or PREFERENCE worth remembering for future sessions -- and write it as a short,
atomic entry. Implements the explicit policy from docs/ARCHITECTURE.md
section 3 ("Write-back policy"):

  1. A small LLM judgment step extracts 0-3 atomic facts (online only).
  2. should_persist() guards each candidate (non-trivial, bounded length).
  3. The store dedups against existing entries before insert.

OFFLINE (no working LLM key configured -- see src/llm.py): capture is
skipped and returns []. Recall is still fully demonstrated against seeded
prior-session memory (see src/memory/seed.py), so `make demo` works with no key.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from src.llm import get_client, get_model, llm_enabled
from src.tracing.models import EvidenceItem, MemoryEntry

logger = logging.getLogger(__name__)

MIN_FACT_LEN = 12
MAX_FACT_LEN = 240


class MemoryCandidate(BaseModel):
    """A proposed memory fact, before the should_persist() guard."""

    text: str = Field(..., description="One atomic fact or preference, one sentence.")
    topic_tags: list[str] = Field(
        default_factory=list, description="1-5 lowercase keyword tags."
    )


class _MemoryCandidates(BaseModel):
    """LLM structured-output envelope."""

    facts: list[MemoryCandidate] = Field(
        default_factory=list,
        description=(
            "0-3 durable facts/preferences worth remembering across sessions. "
            "Empty if nothing is durable."
        ),
    )


def should_persist(candidate: MemoryCandidate) -> bool:
    """Guard: is this candidate a keeper? Cheap, deterministic checks only.

    The real "is this durable?" judgment is made by the LLM in _llm_extract;
    this is the belt-and-suspenders filter that rejects empty, oversized, or
    obviously ephemeral / self-referential text before it reaches the store.
    """
    text = candidate.text.strip()
    if not (MIN_FACT_LEN <= len(text) <= MAX_FACT_LEN):
        return False
    lowered = text.lower()
    banned = ("no evidence", "i could not", "as an ai", "the user asked", "no relevant")
    return not any(b in lowered for b in banned)


def extract_memories(
    question: str,
    answer: str,
    evidence: list[EvidenceItem],
    run_id: str,
) -> list[MemoryEntry]:
    """Return atomic memory entries worth persisting from this exchange.

    Online: one small LLM judgment call. Offline (no key): returns [] -- capture
    is an online-only step by design; recall is proven via seeded memory.
    """
    if not llm_enabled():
        logger.info("Memory write-back skipped (no API key) -- capture is online-only.")
        return []

    candidates = _llm_extract(question, answer, evidence)
    entries: list[MemoryEntry] = []
    for c in candidates:
        if should_persist(c):
            entries.append(
                MemoryEntry(
                    id=uuid.uuid4().hex[:12],
                    text=c.text.strip(),
                    topic_tags=[t.lower() for t in c.topic_tags][:5],
                    created_at=datetime.now(timezone.utc).isoformat(),
                    source_run_id=run_id,
                )
            )
    return entries


def _llm_extract(
    question: str,
    answer: str,
    evidence: list[EvidenceItem],
) -> list[MemoryCandidate]:
    evidence_block = "\n".join(
        f"- ({e.source} {e.id}) {e.text[:200]}" for e in evidence[:8]
    )
    prompt = (
        "You maintain a long-term memory of a software project across sessions. "
        "Memory holds durable FACTS and PREFERENCES, never transcripts, never raw data.\n\n"
        "From the exchange below, extract 0-3 short, atomic facts or preferences that "
        "would still be useful to recall in two weeks (e.g. a decision, a priority, a "
        "deadline change, a stated user preference). If nothing is durable, return an "
        "empty list. One fact per entry, one sentence each, with 1-5 lowercase topic tags.\n\n"
        f"QUESTION: {question}\n\nANSWER: {answer[:1500]}\n\nEVIDENCE:\n{evidence_block}"
    )
    client = get_client()
    try:
        resp = client.beta.chat.completions.parse(
            model=get_model(),
            messages=[{"role": "user", "content": prompt}],
            response_format=_MemoryCandidates,
            temperature=0.1,
        )
        parsed = resp.choices[0].message.parsed
        return parsed.facts if parsed else []
    except Exception as exc:  # noqa: BLE001 -- write-back must never crash a run
        logger.warning("Memory extraction failed: %s", exc)
        return []
