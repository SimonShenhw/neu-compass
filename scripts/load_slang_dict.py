"""Load data/slang_dict.json into course_aliases.

Idempotent (uses AliasRepository.add_or_skip). Entries whose
primary_course_code doesn't exist in the courses table are SKIPPED with a
warning — common case is the slang dict references courses you haven't
seeded yet.

Usage:
    python scripts/load_slang_dict.py
    python scripts/load_slang_dict.py --db-path /tmp/x.db --slang-path other.json

Run order in a fresh DB:
    1. python scripts/seed_aai6600.py            # AAI 6600 + 6 manual aliases
    2. python scripts/seed_synthetic_courses.py  # 6 synthetic courses
    3. python scripts/load_slang_dict.py         # ~40 slang entries
    4. python scripts/rebuild_faiss.py           # vector index over all 7
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from db.alias_repository import AliasRepository  # noqa: E402
from db.connection import connect  # noqa: E402
from schemas.alias import Alias, AliasReviewStatus, AliasSource, AliasType  # noqa: E402

DEFAULT_SLANG_PATH = PROJECT_ROOT / "data" / "slang_dict.json"


@dataclass
class LoadStats:
    """Outcome of one load_slang_dict run."""

    inserted: int = 0
    skipped_already_present: int = 0
    skipped_unknown_course: int = 0
    errors: int = 0


def _resolve_course_code_to_id(
    conn: sqlite3.Connection, primary_code: str,
) -> str | None:
    """Look up course_id by primary_code (case-insensitive). Returns None
    if the course isn't in the DB yet (caller must skip entry)."""
    row = conn.execute(
        "SELECT course_id FROM courses WHERE primary_code = ? COLLATE NOCASE",
        (primary_code,),
    ).fetchone()
    return row["course_id"] if row else None


def load_slang_dict(
    *,
    db_path: str | Path,
    slang_path: str | Path = DEFAULT_SLANG_PATH,
    verbose: bool = True,
) -> LoadStats:
    """Load slang dict into course_aliases. Returns stats."""
    data = json.loads(Path(slang_path).read_text(encoding="utf-8"))
    entries = data.get("entries", [])
    stats = LoadStats()

    conn = connect(db_path)
    try:
        repo = AliasRepository(conn)
        for entry in entries:
            primary_code = entry["primary_course_code"]
            course_id = _resolve_course_code_to_id(conn, primary_code)

            if course_id is None:
                stats.skipped_unknown_course += 1
                if verbose:
                    print(f"  SKIP {entry['alias']!r} -> {primary_code!r} (course not in DB)")
                continue

            try:
                alias = Alias(
                    alias_text=entry["alias"],
                    alias_type=AliasType(entry["alias_type"]),
                    primary_course_id=course_id,
                    source=AliasSource.MANUAL,
                    review_status=AliasReviewStatus.APPROVED,
                    confidence=entry.get("confidence", 0.95),
                )
                result = repo.add_or_skip(alias)
                if result is not None:
                    stats.inserted += 1
                else:
                    stats.skipped_already_present += 1
            except Exception as e:
                stats.errors += 1
                if verbose:
                    print(f"  ERROR {entry['alias']!r}: {type(e).__name__}: {e}")

        conn.commit()
    finally:
        conn.close()

    return stats


def cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default=None,
                        help="Override settings.sqlite_path")
    parser.add_argument("--slang-path", default=None,
                        help="Override data/slang_dict.json path")
    args = parser.parse_args()

    if args.db_path:
        db_path: str | Path = args.db_path
    else:
        from config import settings  # noqa: PLC0415
        db_path = settings.sqlite_path

    slang_path = Path(args.slang_path) if args.slang_path else DEFAULT_SLANG_PATH

    print(f"=> loading {slang_path.name} into {db_path}")
    stats = load_slang_dict(db_path=db_path, slang_path=slang_path)
    print(f"=> inserted              : {stats.inserted}")
    print(f"   skipped (existing)    : {stats.skipped_already_present}")
    print(f"   skipped (course missing): {stats.skipped_unknown_course}")
    print(f"   errors                : {stats.errors}")
    return 1 if stats.errors else 0


if __name__ == "__main__":
    sys.exit(cli())
