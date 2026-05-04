"""Load JSONL CatalogEntry files → CourseRepository.upsert + cross-list aliases.

Two-pass design:
  Pass 1: upsert all Course rows (status='pending'). raw_text = description.
  Pass 2: for each course's cross_listed_codes, add Alias rows pointing at
          the source course (if the target course exists in DB by then).

Run:
    uv run python scripts/ingest_neu_catalog.py
    uv run python scripts/ingest_neu_catalog.py --dept aai
    uv run python scripts/ingest_neu_catalog.py --in /tmp/cat
    uv run python scripts/ingest_neu_catalog.py --dry-run

After ingest, courses.status='pending'. Run scripts/rebuild_faiss.py to embed.

course_id derivation: 'neu-<dept>-<num>' (lowercase). Stable across catalog
re-fetches; matches the existing pattern (e.g. 'neu-aai-6600').
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import settings  # noqa: E402
from db.alias_repository import AliasRepository  # noqa: E402
from db.connection import connect  # noqa: E402
from db.repository import CourseRepository  # noqa: E402
from schemas.alias import (  # noqa: E402
    Alias,
    AliasReviewStatus,
    AliasSource,
    AliasType,
)
from schemas.course import Course  # noqa: E402
from scrapers.neu_catalog import CatalogEntry  # noqa: E402

DEFAULT_IN_DIR = Path(settings.sqlite_path).resolve().parent / "raw" / "neu_catalog"


def course_id_for(code: str) -> str:
    """Stable internal id from canonical code. 'AAI 6600' → 'neu-aai-6600'."""
    dept, num = code.split(" ", 1)
    return f"neu-{dept.lower()}-{num.lower()}"


def load_jsonl(path: Path) -> list[CatalogEntry]:
    out: list[CatalogEntry] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(CatalogEntry.model_validate_json(line))
    return out


def upsert_one(
    entry: CatalogEntry,
    *,
    course_repo: CourseRepository,
) -> str:
    """Pass 1: upsert one CatalogEntry as a Course. Returns the course_id."""
    cid = course_id_for(entry.course_code)
    course = Course(
        course_id=cid,
        primary_code=entry.course_code,
        primary_name=entry.course_name,
        credits=entry.credits,
        prereqs=entry.prereqs,
    )
    # raw_text: feed the catalog description; the embedder will see this.
    course_repo.upsert(course, raw_text=entry.description)
    return cid


def link_cross_list(
    entry: CatalogEntry,
    *,
    source_cid: str,
    course_repo: CourseRepository,
    alias_repo: AliasRepository,
) -> int:
    """Pass 2: add cross-list aliases pointing back to source. Returns count added.

    Skips targets that aren't in DB (orphan cross-list — common when an
    interdisciplinary partner dept's catalog isn't ingested yet)."""
    added = 0
    for target_code in entry.cross_listed_codes:
        target_cid = course_id_for(target_code)
        if not course_repo.exists(target_cid):
            continue
        # Two-way alias: 'AAI 6600' resolves to either course's id, but for
        # primary-vs-cross-listed we record the LINK from this course's id
        # toward the OTHER course's text. Concretely: insert
        # (alias_text=target_code, primary_course_id=source_cid).
        alias = Alias(
            alias_text=target_code,
            alias_type=AliasType.CROSS_LISTED,
            primary_course_id=source_cid,
            confidence=1.0,
            source=AliasSource.OFFICIAL,
            review_status=AliasReviewStatus.APPROVED,
        )
        if alias_repo.add_or_skip(alias) is not None:
            added += 1
    return added


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument(
        "--in", dest="in_dir", type=Path, default=DEFAULT_IN_DIR,
        help=f"Input dir of *.jsonl. Default: {DEFAULT_IN_DIR}",
    )
    p.add_argument("--dept", help="Single dept slug to ingest. Default: all *.jsonl in dir.")
    p.add_argument("--dry-run", action="store_true", help="Parse + report; don't write DB.")
    args = p.parse_args()

    if not args.in_dir.exists():
        print(f"!! input dir not found: {args.in_dir}", file=sys.stderr)
        print("   Run scripts/scrape_neu_catalog.py first.", file=sys.stderr)
        return 2

    files = (
        [args.in_dir / f"{args.dept.lower().strip('/')}.jsonl"]
        if args.dept
        else sorted(args.in_dir.glob("*.jsonl"))
    )
    files = [f for f in files if f.exists()]
    print(f"=> {len(files)} JSONL file(s) to process")
    if not files:
        return 0

    if args.dry_run:
        total = 0
        for f in files:
            entries = load_jsonl(f)
            total += len(entries)
            print(f"  {f.name}: {len(entries)} entries")
        print(f"=> dry-run total: {total} courses")
        return 0

    conn = connect(settings.sqlite_path)
    course_repo = CourseRepository(conn)
    alias_repo = AliasRepository(conn)

    try:
        # Pass 1: upsert all courses
        all_entries: list[tuple[CatalogEntry, str]] = []
        for f in files:
            entries = load_jsonl(f)
            for e in entries:
                cid = upsert_one(e, course_repo=course_repo)
                all_entries.append((e, cid))
            print(f"  pass1 {f.name}: {len(entries)} upserted")

        # Pass 2: link cross-listings (only for courses both ends in DB)
        cross_added = 0
        for entry, source_cid in all_entries:
            cross_added += link_cross_list(
                entry,
                source_cid=source_cid,
                course_repo=course_repo,
                alias_repo=alias_repo,
            )
        print(f"  pass2: {cross_added} cross-list aliases added")

        conn.commit()
        print(f"=> done. {len(all_entries)} courses upserted, {cross_added} aliases linked.")
        print("   Next: run scripts/rebuild_faiss.py to embed (status='pending' → 'indexed').")
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
