"""Enrich one Course's soft fields + evidence_snippets via RMP + Gemini.

Pipeline (PLAN_v2.0 §4.1 Q2=B path):
  Course (catalog/syllabus raw_text)        ─┐
  + RmpProfessorSummary per professor       ─┼─→ assemble_sources
                                             │     ↓ format_sources
                                             │   <source>...</source> XML
                                             │     ↓ build_prompt (extract_v1)
                                             │   Gemini 2.5 Flash
                                             │     ↓ structured output (Course)
                                             └─→ Course with new evidence_snippets

Default is **--dry-run** — prints the assembled prompt + source counts and
exits. `--live` actually calls Gemini (costs API budget, see PLAN §8).
`--save` upserts the enriched Course back to SQLite (only with --live).

Run:
  uv run python scripts/enrich_course_via_rmp.py \\
      --course-id neu-aai-6600 --professor "Pizziferri Hema"
  uv run python scripts/enrich_course_via_rmp.py \\
      --course-id neu-cs-5800 --professor smith --live --save
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import settings  # noqa: E402
from db.connection import connect  # noqa: E402
from db.repository import CourseNotFound, CourseRepository  # noqa: E402
from llm.formatter import format_sources  # noqa: E402
from llm.prompts.extract_v1 import build_prompt  # noqa: E402
from llm.review_enrichment import assemble_sources, enrich_course  # noqa: E402
from scrapers.rmp import RmpProfessorSummary, search_professor  # noqa: E402


def fetch_rmp(names: list[str]) -> list[RmpProfessorSummary]:
    """Look up each professor on RMP. Logs misses but doesn't fail the whole
    enrichment — a course with one missing prof + one match still gets useful
    data.
    """
    out: list[RmpProfessorSummary] = []
    for name in names:
        try:
            summary = search_professor(name)
        except Exception as e:
            print(f"  RMP: {name!r} → ERROR {type(e).__name__}: {e}")
            continue
        if summary is None:
            print(f"  RMP: {name!r} → no match")
            continue
        out.append(summary)
        print(
            f"  RMP: {name!r} → {summary.name} "
            f"({summary.department}, {summary.num_ratings} ratings, "
            f"{len(summary.reviews)} reviews pulled)"
        )
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--course-id", required=True, help="e.g. 'neu-aai-6600'")
    p.add_argument(
        "--professor", action="append", default=[],
        help="Professor name to look up on RMP. Repeat for multiple profs. "
             "If omitted, falls back to course.professor from DB.",
    )
    p.add_argument(
        "--live", action="store_true",
        help="Call Gemini (default: dry-run prints prompt + exits).",
    )
    p.add_argument(
        "--save", action="store_true",
        help="Upsert enriched Course back to SQLite (only with --live).",
    )
    args = p.parse_args()

    conn = connect(settings.sqlite_path)
    course_repo = CourseRepository(conn)
    try:
        try:
            course = course_repo.get(args.course_id)
        except CourseNotFound:
            print(f"ERROR: course {args.course_id!r} not in DB", file=sys.stderr)
            return 2

        row = conn.execute(
            "SELECT raw_text FROM courses WHERE course_id = ?",
            (args.course_id,),
        ).fetchone()
        raw_text = row["raw_text"] if row else None

        names = args.professor or list(course.professor)
        if not names:
            print(
                "ERROR: no professor known. Pass --professor 'First Last' "
                "or seed course.professor before running.",
                file=sys.stderr,
            )
            return 2

        print(f"=> course: {course.primary_code} — {course.primary_name}")
        print(f"=> raw_text: {len(raw_text) if raw_text else 0} chars")
        print(f"=> looking up {len(names)} professor(s) on RMP")
        summaries = fetch_rmp(names)
        print(
            f"=> assembled {sum(len(s.reviews) for s in summaries)} reviews "
            f"across {len(summaries)} professor(s)"
        )

        docs = assemble_sources(course, raw_text, summaries)
        sources_xml = format_sources(docs)
        prompt = build_prompt(sources_xml)
        print(f"=> prompt: {len(docs)} sources, {len(prompt)} chars")

        if not args.live:
            print("\n=== DRY RUN — pass --live to call Gemini ===\n")
            preview = prompt if len(prompt) < 3000 else prompt[:1500] + \
                f"\n\n... [{len(prompt) - 3000} chars trimmed] ...\n\n" + \
                prompt[-1500:]
            print(preview)
            return 0

        print("=> calling Gemini ...")
        enriched = enrich_course(course, raw_text, summaries)
        print(f"=> got Course: {enriched.primary_code} — {enriched.primary_name}")
        print(f"   evidence_snippets: {len(enriched.evidence_snippets)}")
        print(f"   difficulty_score:  {enriched.difficulty_score}")
        print(f"   workload_hours/wk: {enriched.workload_hours_per_week}")
        print(f"   skill_tags:        {enriched.skill_tags}")
        print(f"   topics_covered:    {enriched.topics_covered[:5]}{'...' if len(enriched.topics_covered) > 5 else ''}")

        if args.save:
            course_repo.upsert(enriched, raw_text=raw_text)
            conn.commit()
            print("=> saved (status reset to 'pending'; rerun rebuild_faiss to re-embed)")
        else:
            print("=> --save not passed; not persisted")

        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
