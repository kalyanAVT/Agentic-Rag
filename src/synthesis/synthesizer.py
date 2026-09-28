"""
Synthesis — produce a cited answer from evidence.

Phase 1: real OpenAI call with fallback to placeholder if no API key.
"""

from __future__ import annotations

import logging
import re

from src.llm import get_client, get_model, llm_enabled
from src.tracing.models import Citation, EvidenceItem, MemoryEntry, PlanStep

logger = logging.getLogger(__name__)


def _build_prompt(
    question: str,
    plan: list[PlanStep],
    evidence: list[EvidenceItem],
    memory: list[MemoryEntry] | None = None,
) -> str:
    """Build the synthesis prompt with numbered evidence items."""
    evidence_block = "\n".join(
        f"[E{i+1}] ({e.source} {e.id}): {e.text}"
        for i, e in enumerate(evidence)
    )

    plan_block = "\n".join(
        f"  {i+1}. {step.sub_question}" for i, step in enumerate(plan)
    )

    memory_block = ""
    if memory:
        recalled = "\n".join(f"[M{i+1}] {m.text}" for i, m in enumerate(memory))
        memory_block = f"""

MEMORY RECALLED FROM PRIOR SESSIONS:
{recalled}

When prior memory is relevant, state what was previously decided and whether the
current evidence shows it is still on track or has changed. Cite memory as [M1], [M2]."""

    return f"""You are a project analyst. Answer the user's question using ONLY the
evidence provided below. Cite every factual claim using the evidence tags
(e.g. [E1], [E2]). If evidence is insufficient for part of the question,
say so explicitly — do not fabricate information.

QUESTION: {question}

PLAN (sub-questions investigated):
{plan_block}

EVIDENCE:
{evidence_block}{memory_block}

Provide a clear, structured answer with inline citations like [E1], [E2], etc."""


def _parse_citations(
    answer: str,
    evidence: list[EvidenceItem],
) -> list[Citation]:
    """Extract [E1], [E2], ... citation tags from the answer and map them back."""
    tags = set(re.findall(r"\[E(\d+)\]", answer))
    citations: list[Citation] = []

    for tag in sorted(tags, key=int):
        idx = int(tag) - 1
        if 0 <= idx < len(evidence):
            e = evidence[idx]
            citations.append(Citation(
                claim=f"[E{tag}]",
                evidence_id=e.id,
                url=e.url,
            ))

    return citations


def synthesize(
    question: str,
    plan: list[PlanStep],
    evidence: list[EvidenceItem],
    memory: list[MemoryEntry] | None = None,
) -> tuple[str, list[Citation]]:
    """
    Generate a cited answer from the question, plan, and evidence.

    Uses the configured LLM if a real API key is set; otherwise falls back
    to a simple concatenation so `make demo` works without credentials. Any
    relevant long-term `memory` is woven in so the answer can reference
    what prior sessions decided (see docs/ARCHITECTURE.md section 3).
    """
    prompt = _build_prompt(question, plan, evidence, memory)

    if llm_enabled():
        try:
            answer = _call_openai(prompt)
        except Exception as exc:  # noqa: BLE001 - any API failure degrades gracefully
            logger.warning(
                "Synthesis LLM call failed (%s); using offline fallback.", exc
            )
            answer = _fallback_synthesis(question, plan, evidence, memory)
    else:
        answer = _fallback_synthesis(question, plan, evidence, memory)

    citations = _parse_citations(answer, evidence)
    return answer, citations


def _call_openai(prompt: str) -> str:
    """Make a real LLM API call for synthesis (OpenAI-compatible provider).

    Raises if the provider returns empty content so the caller degrades to the
    offline fallback -- an honest evidence digest beats a blank, citation-less
    answer (some free-tier backends occasionally return empty completions).
    """
    client = get_client()
    response = client.chat.completions.create(
        model=get_model(),
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=1024,
    )
    answer = (response.choices[0].message.content or "").strip()
    if not answer:
        raise ValueError("LLM returned empty content")
    return answer


def _fallback_synthesis(
    question: str,
    plan: list[PlanStep],
    evidence: list[EvidenceItem],
    memory: list[MemoryEntry] | None = None,
) -> str:
    """
    Heuristic synthesis when no API key is available.

    Presents the plan, any recalled long-term memory, and the evidence actually
    gathered (with citation tags) so `make demo` shows a complete, honest trace
    without an LLM. Set a real LLM API key for a real analytical, cited answer.
    """
    lines = [
        "## Answer (fallback - no LLM API key set)\n",
        f"**Question:** {question}\n",
        "**Sub-questions investigated:**\n",
    ]
    for i, step in enumerate(plan):
        hint = f" (via {step.tool_hint})" if step.tool_hint else ""
        lines.append(f"{i + 1}. {step.sub_question}{hint}\n")

    lines.append("")
    if memory:
        lines.append(f"**Recalled from prior sessions ({len(memory)}):**\n")
        for k, m in enumerate(memory):
            lines.append(f"- [M{k + 1}] {m.text}\n")
        lines.append("")

    if evidence:
        lines.append(f"**Evidence collected ({len(evidence)} items):**\n")
        for j, e in enumerate(evidence):
            snippet = e.text[:200].replace("\n", " ")
            lines.append(f"- [E{j + 1}] ({e.source} {e.id}): {snippet}\n")
    else:
        lines.append("_The tools returned no evidence for this question._\n")

    return "\n".join(lines)
