"""
Tests for TraceStore -- JSON persistence + retrieval round-trip (Phase 5).

These are pure-disk tests: no LLM, no network. Each test points the store at a
pytest ``tmp_path`` so nothing touches the real ./traces directory.
"""

from __future__ import annotations

from src.tracing.models import Citation, EvidenceItem, PlanStep, Trace
from src.tracing.store import TraceStore


def _make_trace(run_id: str = "abc12345", question: str = "What changed?") -> Trace:
    return Trace(
        run_id=run_id,
        question=question,
        plan=[PlanStep(sub_question="What merged?", tool_hint="search_pull_requests")],
        evidence=[
            EvidenceItem(source="pr", id="pr-1", text="Merged the pagination fix", url="http://x/1")
        ],
        answer="The pagination fix merged [E1].",
        citations=[Citation(claim="pagination fix merged", evidence_id="E1", url="http://x/1")],
        timing_ms={"total_ms": 5},
    )


def test_save_creates_named_json_file(tmp_path):
    store = TraceStore(trace_dir=str(tmp_path))
    path = store.save(_make_trace())

    assert path.exists()
    assert path.suffix == ".json"
    assert path.name.endswith("-abc12345.json")  # <timestamp>-<run_id>.json


def test_save_then_load_round_trips_the_trace(tmp_path):
    store = TraceStore(trace_dir=str(tmp_path))
    store.save(_make_trace(run_id="deadbeef", question="Round trip?"))

    loaded = store.load("deadbeef")

    assert loaded is not None
    assert loaded.run_id == "deadbeef"
    assert loaded.question == "Round trip?"
    # Nested models survive the JSON round-trip.
    assert loaded.evidence[0].id == "pr-1"
    assert loaded.citations[0].evidence_id == "E1"


def test_list_runs_returns_a_summary_per_saved_trace(tmp_path):
    store = TraceStore(trace_dir=str(tmp_path))
    store.save(_make_trace(run_id="run00001", question="First"))
    store.save(_make_trace(run_id="run00002", question="Second"))

    runs = store.list_runs()

    assert len(runs) == 2
    assert {r["run_id"] for r in runs} == {"run00001", "run00002"}
    # Summaries carry preview fields, not the full trace.
    for r in runs:
        assert set(r) >= {"run_id", "question", "answer_preview", "n_evidence", "file"}
        assert r["n_evidence"] == 1


def test_load_missing_run_returns_none(tmp_path):
    store = TraceStore(trace_dir=str(tmp_path))
    store.save(_make_trace(run_id="present1"))

    assert store.load("absent99") is None


def test_load_from_nonexistent_dir_returns_none(tmp_path):
    store = TraceStore(trace_dir=str(tmp_path / "never-created"))
    assert store.load("anything") is None


def test_list_runs_on_empty_or_missing_dir_is_empty(tmp_path):
    # Missing directory.
    assert TraceStore(trace_dir=str(tmp_path / "missing")).list_runs() == []
    # Existing but empty directory.
    empty = tmp_path / "empty"
    empty.mkdir()
    assert TraceStore(trace_dir=str(empty)).list_runs() == []


def test_corrupt_file_is_skipped_not_fatal(tmp_path):
    store = TraceStore(trace_dir=str(tmp_path))
    store.save(_make_trace(run_id="good0001"))
    # Drop a non-JSON file alongside a valid one.
    (tmp_path / "20990101T000000Z-bad00001.json").write_text("{ not valid json", encoding="utf-8")

    runs = store.list_runs()

    # Corrupt file ignored; the good one still lists and loads.
    assert [r["run_id"] for r in runs] == ["good0001"]
    assert store.load("bad00001") is None
