"""
Pydantic models for the full trace object.

These models define the structured output of every agent run — plan, tool calls,
evidence, memory, answer, and citations. They are the spine of the entire system
and are used by the API, the frontend, and observability integrations.

Spec: docs/ARCHITECTURE.md § 5 (Tracing / observability)
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PlanStep(BaseModel):
    """A single sub-question in the decomposed plan."""

    sub_question: str
    tool_hint: str | None = None


class ToolCall(BaseModel):
    """Record of a single tool invocation and its result."""

    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)
    result: Any = None
    latency_ms: int = 0
    success: bool = True


class EvidenceItem(BaseModel):
    """A normalized piece of evidence retrieved by a tool call."""

    source: str  # e.g. "issue", "pull_request", "commit"
    id: str  # e.g. "issue-3", "pr-101"
    text: str
    url: str = ""
    timestamp: str = ""


class MemoryEntry(BaseModel):
    """A single persisted memory fact."""

    id: str
    text: str
    topic_tags: list[str] = Field(default_factory=list)
    created_at: str = ""
    source_run_id: str = ""
    # GitHub repo ("owner/name") this fact is about; "" = the offline seed demo.
    # Recall only returns facts from the same repo, so one repo's facts never
    # show up as [M#] citations in an answer about another.
    repo: str = ""


class Citation(BaseModel):
    """Maps a claim in the answer to an evidence item."""

    claim: str
    evidence_id: str
    url: str = ""


class Trace(BaseModel):
    """
    Full structured trace of a single agent run.

    This is the centerpiece of the demo — every run produces one of these,
    and the frontend renders it step-by-step.
    """

    run_id: str
    question: str
    # Canonical "owner/name" of the GitHub repo this run queried, when the caller
    # supplied one; None for the offline seed demo. Optional so already-persisted
    # trace JSON (which lacks the field) still validates.
    repo: str | None = None
    # True when the run used the visitor's GitHub token (a private repo): the
    # Trace is returned to that caller only -- never saved to /runs, never
    # written to shared memory, never sent to Langfuse.
    private: bool = False
    memory_used: list[MemoryEntry] = Field(default_factory=list)
    plan: list[PlanStep] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    memory_written: list[MemoryEntry] = Field(default_factory=list)
    answer: str = ""
    citations: list[Citation] = Field(default_factory=list)
    timing_ms: dict[str, int] = Field(default_factory=dict)
