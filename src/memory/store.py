"""
Long-term memory store (SQLite).

Persists atomic FACTS and PREFERENCES across sessions -- never transcripts or
raw tool output (see docs/ARCHITECTURE.md section 3). Retrieval and dedup use
lightweight keyword / topic-tag overlap: no embeddings, no API key, identical
behavior online and offline. The point being demonstrated is the write-back
POLICY, not a fancy vector DB -- swap in Postgres + pgvector to scale (see
ARCHITECTURE.md "Extension points").
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from src.tracing.models import MemoryEntry

# Default DB lives alongside the seed data; override with MEMORY_DB_PATH.
_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "memory.db"

# Tuning knobs -- intentionally simple.
MAX_ENTRIES = 200          # cap total memory; evict oldest beyond this
DEDUP_THRESHOLD = 0.6      # Jaccard token overlap above which entries are "the same"
DEFAULT_TOP_K = 3          # entries fed into the planner / synthesis per run

_STOPWORDS = {
    "what", "were", "are", "the", "this", "that", "how", "why", "and", "or",
    "for", "in", "on", "at", "to", "of", "a", "an", "is", "was", "has", "have",
    "been", "any", "which", "did", "we", "our", "us", "about", "with", "still",
    "it", "its", "do", "does", "last", "week", "quarter", "there", "their",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tokenize(text: str) -> set[str]:
    """Lowercase alphanumeric tokens, minus stopwords and very short words."""
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return {t for t in tokens if len(t) >= 3 and t not in _STOPWORDS}


def _entry_tokens(text: str, tags: list[str]) -> set[str]:
    toks = _tokenize(text)
    for tag in tags:
        toks |= _tokenize(tag)
    return toks


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class MemoryStore:
    """SQLite-backed long-term memory of atomic facts / preferences."""

    def __init__(self, db_path: str | os.PathLike | None = None) -> None:
        path = db_path or os.getenv("MEMORY_DB_PATH") or _DEFAULT_DB_PATH
        self.db_path = str(path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id            TEXT PRIMARY KEY,
                text          TEXT NOT NULL,
                topic_tags    TEXT NOT NULL DEFAULT '[]',
                created_at    TEXT NOT NULL,
                source_run_id TEXT NOT NULL DEFAULT ''
            )
            """
        )
        self._conn.commit()

    # -- reads --------------------------------------------------------------

    def all(self) -> list[MemoryEntry]:
        rows = self._conn.execute(
            "SELECT * FROM memories ORDER BY created_at ASC"
        ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

    def retrieve(self, question: str, k: int = DEFAULT_TOP_K) -> list[MemoryEntry]:
        """Return up to k entries most relevant to the question.

        Relevance = shared tokens between the question and each entry, with
        topic-tag matches weighted double. Entries with zero overlap are
        excluded -- we feed the planner only what is relevant, not the whole
        store (see ARCHITECTURE.md section 3, "Retrieval").
        """
        q_tokens = _tokenize(question)
        if not q_tokens:
            return []

        scored: list[tuple[int, str, MemoryEntry]] = []
        for entry in self.all():
            text_tokens = _tokenize(entry.text)
            tag_tokens: set[str] = set()
            for tag in entry.topic_tags:
                tag_tokens |= _tokenize(tag)
            score = len(q_tokens & text_tokens) + 2 * len(q_tokens & tag_tokens)
            if score > 0:
                # created_at as tiebreaker (newer first)
                scored.append((score, entry.created_at, entry))

        scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
        return [entry for _, _, entry in scored[:k]]

    # -- writes -------------------------------------------------------------

    def add(self, entry: MemoryEntry) -> bool:
        """Insert an entry unless a near-duplicate already exists.

        Dedup: Jaccard overlap of token sets >= DEDUP_THRESHOLD. Enforces
        MAX_ENTRIES by evicting the oldest entries. Returns True if inserted.
        """
        new_tokens = _entry_tokens(entry.text, entry.topic_tags)
        for existing in self.all():
            ex_tokens = _entry_tokens(existing.text, existing.topic_tags)
            if _jaccard(new_tokens, ex_tokens) >= DEDUP_THRESHOLD:
                return False  # near-duplicate; skip

        eid = entry.id or uuid.uuid4().hex[:12]
        created = entry.created_at or _now_iso()
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO memories "
            "(id, text, topic_tags, created_at, source_run_id) VALUES (?, ?, ?, ?, ?)",
            (eid, entry.text, json.dumps(entry.topic_tags), created, entry.source_run_id),
        )
        self._conn.commit()
        self._enforce_cap()
        return cur.rowcount > 0

    def clear(self) -> None:
        self._conn.execute("DELETE FROM memories")
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # -- internals ----------------------------------------------------------

    def _enforce_cap(self) -> None:
        n = self.count()
        if n > MAX_ENTRIES:
            self._conn.execute(
                "DELETE FROM memories WHERE id IN ("
                "SELECT id FROM memories ORDER BY created_at ASC LIMIT ?)",
                (n - MAX_ENTRIES,),
            )
            self._conn.commit()

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> MemoryEntry:
        try:
            tags = json.loads(row["topic_tags"])
        except (json.JSONDecodeError, TypeError):
            tags = []
        return MemoryEntry(
            id=row["id"],
            text=row["text"],
            topic_tags=tags,
            created_at=row["created_at"],
            source_run_id=row["source_run_id"],
        )
