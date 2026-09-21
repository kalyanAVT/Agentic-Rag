"""Tests for Pydantic trace models."""

from src.tracing.models import (
    Citation,
    EvidenceItem,
    MemoryEntry,
    PlanStep,
    ToolCall,
    Trace,
)


def test_plan_step_creation() -> None:
    step = PlanStep(sub_question="What changed?", tool_hint="search_issues")
    assert step.sub_question == "What changed?"
    assert step.tool_hint == "search_issues"


def test_plan_step_optional_hint() -> None:
    step = PlanStep(sub_question="What changed?")
    assert step.tool_hint is None


def test_evidence_item() -> None:
    e = EvidenceItem(source="issue", id="issue-1", text="test text")
    assert e.source == "issue"
    assert e.url == ""


def test_trace_serialization() -> None:
    trace = Trace(
        run_id="test-123",
        question="What changed?",
        plan=[PlanStep(sub_question="Sub Q1")],
        tool_calls=[ToolCall(tool_name="search_issues", args={"query": "test"})],
        evidence=[EvidenceItem(source="issue", id="issue-1", text="text")],
        answer="Test answer [E1]",
        citations=[Citation(claim="[E1]", evidence_id="issue-1", url="http://example.com")],
        timing_ms={"total_ms": 100},
    )

    # Round-trip through JSON
    json_str = trace.model_dump_json()
    restored = Trace.model_validate_json(json_str)
    assert restored.run_id == "test-123"
    assert len(restored.plan) == 1
    assert len(restored.citations) == 1


def test_trace_defaults() -> None:
    trace = Trace(run_id="t", question="q")
    assert trace.memory_used == []
    assert trace.memory_written == []
    assert trace.plan == []
    assert trace.timing_ms == {}
