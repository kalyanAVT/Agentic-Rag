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
    memory_used: list[MemoryEntry] = Field(default_factory=list)
    plan: list[PlanStep] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    memory_written: list[MemoryEntry] = Field(default_factory=list)
    answer: str = ""
    citations: list[Citation] = Field(default_factory=list)
    timing_ms: dict[str, int] = Field(default_factory=dict)
