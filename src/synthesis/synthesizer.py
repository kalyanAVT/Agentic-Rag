"""
Synthesis — produce a cited answer from evidence.

Phase 1: real OpenAI call with fallback to placeholder if no API key.
"""

from __future__ import annotations

import os
import re

from src.tracing.models import Citation, EvidenceItem, PlanStep


def _build_prompt(
    question: str,
    plan: list[PlanStep],
    evidence: list[EvidenceItem],
) -> str:
    """Build the synthesis prompt with numbered evidence items."""
    evidence_block = "\n".join(
        f"[E{i+1}] ({e.source} {e.id}): {e.text}"
        for i, e in enumerate(evidence)
    )

    plan_block = "\n".join(
        f"  {i+1}. {step.sub_question}" for i, step in enumerate(plan)
    )

    return f"""You are a project analyst. Answer the user's question using ONLY the
evidence provided below. Cite every factual claim using the evidence tags
(e.g. [E1], [E2]). If evidence is insufficient for part of the question,
say so explicitly — do not fabricate information.

QUESTION: {question}

PLAN (sub-questions investigated):
{plan_block}

EVIDENCE:
{evidence_block}

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
) -> tuple[str, list[Citation]]:
    """
    Generate a cited answer from the question, plan, and evidence.

    Uses OpenAI if OPENAI_API_KEY is set; otherwise falls back to a
    simple concatenation so `make demo` works without credentials.
    """
    prompt = _build_prompt(question, plan, evidence)
    api_key = os.getenv("OPENAI_API_KEY", "")

    if api_key and api_key != "sk-change-me":
        answer = _call_openai(prompt, api_key)
    else:
        answer = _fallback_synthesis(question, plan, evidence)

    citations = _parse_citations(answer, evidence)
    return answer, citations


def _call_openai(prompt: str, api_key: str) -> str:
    """Make a real OpenAI API call for synthesis."""
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=1024,
    )
    return response.choices[0].message.content or ""


def _fallback_synthesis(
    question: str,
    plan: list[PlanStep],
    evidence: list[EvidenceItem],
) -> str:
    """
    Fallback synthesis when no API key is available.
    Produces a reasonable answer by summarizing the evidence directly.
    """
    lines = [
        f"## Answer (fallback — no LLM API key set)\n",
        f"**Question:** {question}\n",
        "**Summary based on available evidence:**\n",
    ]

    for i, step in enumerate(plan):
        lines.append(f"### {step.sub_question}\n")
        relevant = [
            (j, e) for j, e in enumerate(evidence)
            if any(
                keyword in e.text.lower()
                for keyword in step.sub_question.lower().split()[:3]
            )
        ]
        if relevant:
            for j, e in relevant:
                lines.append(f"- {e.text[:200]}... [E{j+1}]\n")
        else:
            lines.append("- No directly matching evidence found.\n")

    return "\n".join(lines)
