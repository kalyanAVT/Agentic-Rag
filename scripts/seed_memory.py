"""
Seed script -- populates the LONG-TERM MEMORY store with prior-session facts.

The memory analog of scripts/seed_github.py: instead of seeding the GitHub
repo, it seeds src/memory (SQLite) with the durable facts a prior session would
have captured, so the cross-session recall demo has something to recall.
Idempotent -- safe to run repeatedly.

Usage:
    python scripts/seed_memory.py                 # seed the default DB
    python scripts/seed_memory.py --db some.db    # seed a specific DB
    python scripts/seed_memory.py --list          # list current memory and exit
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running as a plain script (python scripts/seed_memory.py) by putting the
# repo root -- not scripts/ -- on the import path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.memory.seed import seed_prior_session  # noqa: E402
from src.memory.store import MemoryStore  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the long-term memory store")
    parser.add_argument(
        "--db",
        default=None,
        help="Path to the SQLite memory DB (default: src/data/memory.db or $MEMORY_DB_PATH)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List current memory and exit (no seeding)",
    )
    args = parser.parse_args()

    store = MemoryStore(args.db)

    if args.list:
        entries = store.all()
        print(f"{len(entries)} memory entries in {store.db_path}:")
        for e in entries:
            print(f"  - [{e.id}] {e.text}  <{', '.join(e.topic_tags)}>")
        store.close()
        return

    inserted = seed_prior_session(store)
    print(
        f"Seeded {inserted} new prior-session fact(s); "
        f"{store.count()} total in {store.db_path}."
    )
    store.close()


if __name__ == "__main__":
    main()
