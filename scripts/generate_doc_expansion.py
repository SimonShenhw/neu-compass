"""Offline doc2query expansion + zh keywords + acronym mining (ADR-0020).

One-time (per corpus version) Gemini batch over every indexed course.
Output feeds three retrieval fixes at ZERO per-query cost:

  1. doc2query (Nogueira lineage, LLM flavor): realistic student queries
     appended to each course's BM25 document — attacks the medium-tier
     paraphrase ceiling (R@5 0.61 vs 0.91 for code lookups) by closing
     the vocabulary gap from the DOCUMENT side.
  2. Chinese keywords per course — paired with CJK-bigram tokenization
     (rag/hybrid.tokenize), this gives 中文 queries a lexical channel for
     the first time (bge-m3's own paper: sparse signal is near-useless
     cross-lingually; BM25 leg was ASCII-only).
  3. Acronym mining — "CRM" in a healthcare course means Crisis Resource
     Management; the corpus itself disambiguates. Aggregated into
     data/acronym_glossary.json by scripts/apply_doc_expansion.py.

Resumable: writes JSONL incrementally; rerun skips course_ids already
present in --out. ~810 batched calls for 6.4k courses, 20-40 min, <$2.

Usage (PC WSL, needs GEMINI_API_KEY in .env):
    uv run python scripts/generate_doc_expansion.py \
        --db-path ~/neu-compass-data/courses.db
Then filter + apply: see scripts/apply_doc_expansion.py (filtering with
the int8 reranker runs on the NAS, Doc2Query-- style).
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BATCH_SIZE = 8
# Sequential + default thinking measured ~17 courses/min (≈6h for the
# corpus). thinking_budget=0 (this is mechanical extraction, not judgment)
# + 6 workers brings it to ~40min. Gemini Tier-1 rate limits absorb this.
MAX_WORKERS = 6


class AcronymDef(BaseModel):
    acronym: str = Field(description="Uppercase acronym, 2-6 letters")
    expansion: str = Field(description="Its long form as used in THIS course")


class CourseExpansion(BaseModel):
    course_id: str
    student_queries: list[str] = Field(
        description="4 realistic English search queries a student would type "
        "to find this course WITHOUT reusing its title words"
    )
    zh_keywords: list[str] = Field(
        description="2-3 Chinese keyword phrases (3-10 字) a Chinese graduate "
        "student would search for this course's topics"
    )
    keywords: list[str] = Field(
        description="3-5 English topic/keyword phrases not already prominent "
        "in the title"
    )
    acronyms: list[AcronymDef] = Field(
        description="Acronyms appearing in or strongly implied by the course "
        "text, with the expansion THIS course context implies. Empty if none."
    )


class ExpansionBatch(BaseModel):
    items: list[CourseExpansion]


PROMPT_HEADER = """You generate search-index expansion data for a university \
course catalog. For EACH course below, produce the fields described by the \
schema. Rules:
- student_queries: how real graduate students search — interests, skills, \
career goals; NEVER copy the course title phrasing.
- zh_keywords: natural Chinese search phrases for the same topics (mixed \
EN jargon inside Chinese is fine).
- acronyms: only acronyms grounded in the course text/topic; expansion must \
match THIS course's meaning (e.g. CRM in a healthcare-teamwork course is \
"Crisis Resource Management", not customer relationship management).
- Use the exact course_id strings given.

Courses:
"""


def _format_course(row) -> str:
    return (
        f"- course_id: {row['course_id']} | {row['primary_code']} "
        f"{row['primary_name']}\n  text: {(row['raw_text'] or '')[:400]}"
    )


def cli() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db-path", required=True)
    ap.add_argument(
        "--out",
        default=str(PROJECT_ROOT / "data" / "doc_expansion" / "expansions.jsonl"),
    )
    ap.add_argument("--limit", type=int, default=0, help="0 = all courses")
    args = ap.parse_args()

    from db.connection import connect  # noqa: PLC0415
    from llm.gemini_client import GeminiError, generate_structured  # noqa: PLC0415

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    done: set[str] = set()
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(line)["course_id"])
            except Exception:  # noqa: BLE001 — tolerate a torn tail line
                continue
    print(f"=> resuming: {len(done)} courses already expanded")

    conn = connect(str(Path(args.db_path).expanduser()))
    try:
        rows = conn.execute(
            "SELECT course_id, primary_code, primary_name, raw_text FROM courses "
            "WHERE status='indexed' AND length(COALESCE(raw_text,'')) >= 60 "
            "ORDER BY course_id"
        ).fetchall()
    finally:
        conn.close()

    todo = [r for r in rows if r["course_id"] not in done]
    if args.limit:
        todo = todo[: args.limit]
    print(f"=> {len(todo)} courses to expand ({len(rows)} eligible total)")

    batches = [todo[i : i + BATCH_SIZE] for i in range(0, len(todo), BATCH_SIZE)]
    n_ok = n_fail = n_done = 0
    write_lock = threading.Lock()

    def run_batch(batch) -> tuple[int, int, list[str]]:
        wanted = {r["course_id"] for r in batch}
        prompt = PROMPT_HEADER + "\n".join(_format_course(r) for r in batch)
        try:
            result = generate_structured(
                prompt, schema=ExpansionBatch, temperature=0.4,
                thinking_budget=0,
            )
        except GeminiError as e:
            return 0, len(batch), [f"{batch[0]['course_id']}...: {str(e)[:100]}"]
        lines = [
            item.model_dump_json()
            for item in result.items
            if item.course_id in wanted  # drop hallucinated ids
        ]
        with write_lock:
            with out_path.open("a", encoding="utf-8") as fh:
                fh.write("".join(line + "\n" for line in lines))
        return len(lines), 0, []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = [pool.submit(run_batch, b) for b in batches]
        for fut in as_completed(futures):
            ok, fail, errors = fut.result()
            n_ok += ok
            n_fail += fail
            n_done += 1
            for err in errors:
                print(f"   ! batch failed: {err}")
            if n_done % 20 == 0:
                print(f"   {n_done}/{len(batches)} batches "
                      f"(ok={n_ok} fail={n_fail})")

    print(f"\n=> done: ok={n_ok} fail={n_fail} -> {out_path}")
    print("   next: scripts/apply_doc_expansion.py (filter on NAS, then apply)")
    return 0


if __name__ == "__main__":
    sys.exit(cli())
