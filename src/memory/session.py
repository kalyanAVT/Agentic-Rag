"""
Short-term (session) memory -- in-process working memory for ONE run.

Holds the sub-questions asked and the evidence gathered so far, so a run does
not re-fetch or double-count what it already has. Never persisted (see
docs/ARCHITECTURE.md section 3, "Short-term (session) memory"). This formalizes
the ad-hoc dedup that previously lived inline in src/demo.py.
"""

from __future__ import annotations

from src.tracing.models import EvidenceItem, PlanStep


class SessionMemory:
    """Ephemeral per-run working memory. Discarded when the run ends."""

    def __init__(self) -> None:
        self.sub_questions: list[str] = []
        self._evidence: list[EvidenceItem] = []
        self._seen_ids: set[str] = set()

    def record_step(self, step: PlanStep) -> None:
        """Note that a sub-question is being investigated this run."""
        self.sub_questions.append(step.sub_question)

    def add_evidence(self, items: list[EvidenceItem]) -> list[EvidenceItem]:
        """Append new evidence, deduped by id. Returns the items actually added."""
        added: list[EvidenceItem] = []
        for item in items:
            if item.id not in self._seen_ids:
                self._seen_ids.add(item.id)
                self._evidence.append(item)
                added.append(item)
        return added

    @property
    def evidence(self) -> list[EvidenceItem]:
        """All unique evidence gathered so far this run (in arrival order)."""
        return list(self._evidence)
