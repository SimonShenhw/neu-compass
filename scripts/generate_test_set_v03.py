"""Generate eval/test_set_v03.json — the n≥100 set ADR-0015/0016 mandate.

Why now: every tuning decision so far (α=0.4, T=0.05→gate, pool 10) was
locked on n=42, where a paired test only distinguishes R@5 deltas ≥~0.10
(Urbano, SIGIR'19). Real query logs are still thin (soft launch), so v0.3
expands from the corpus itself + LLM paraphrasing — the ARES/UMBRELA
recipe adapted to zero-traffic conditions.

Composition (≈104 total):
  - ALL 42 v0.2 queries verbatim (continuity: v0.2 numbers stay comparable)
  - +18 simple    code-format variants across departments (alias tier)
  - +18 medium    Gemini-paraphrased natural queries, told to AVOID the
                  course title words (tests semantics, not string match)
  - +12 complex   Gemini constraint-style queries (level/format/topic mix)
  - +6  boundary  Chinese-language intent queries (bilingual audience)
  - +8  adversarial hand-written, fresh wording (deliberately disjoint
                  from the ADR-0018 gate-calibration set to avoid coupling)

Ground truth: each generated query's expected_course_ids = the source
course (weak-label convention — "the known-relevant item must rank top-5";
same semantics as v0.2). Every id is validated against the live DB
(exists + status='indexed') before write.

Usage (WSL, needs GEMINI_API_KEY in .env; ~36 Flash calls):
    uv run python scripts/generate_test_set_v03.py \
        --db-path ~/neu-compass-data/courses.db
    uv run python scripts/generate_test_set_v03.py --no-llm   # skeleton only
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Fresh adversarial wording — none of these appear in test_set v0.2 OR in
# scripts/calibrate_rejection.py's UNANSWERABLE_QUERIES (gate must not be
# evaluated on its own training phrasing).
NEW_ADVERSARIAL: list[str] = [
    "EECE 0000",
    "BINF 99999 advanced seminar",
    "Oxford PPE admissions requirements",
    "UCLA CS 188 reinforcement learning",
    "library printing quota per semester",
    "wpeofij qwelkrj zxocvib",
    "registrar office phone number please",
    "course that teaches time travel paradox engineering",
]


def _sample_courses(conn, *, n: int, seed: int, min_text: int = 120) -> list:
    """Department-stratified deterministic sample of indexed courses."""
    rows = conn.execute(
        "SELECT course_id, primary_code, primary_name, raw_text FROM courses "
        "WHERE status='indexed' AND length(COALESCE(raw_text,'')) >= ? "
        "ORDER BY course_id",
        (min_text,),
    ).fetchall()
    by_dept: dict[str, list] = {}
    for r in rows:
        dept = r["primary_code"].split()[0]
        by_dept.setdefault(dept, []).append(r)

    rng = random.Random(seed)
    depts = sorted(by_dept)
    rng.shuffle(depts)
    picked, i = [], 0
    while len(picked) < n and depts:
        dept = depts[i % len(depts)]
        bucket = by_dept[dept]
        if bucket:
            picked.append(bucket.pop(rng.randrange(len(bucket))))
        else:
            depts.remove(dept)
            continue
        i += 1
    return picked


def _code_variant(code: str, style: int) -> str:
    """simple-category formats the alias tier must absorb."""
    if style == 0:
        return code                              # "CSYE 6200"
    if style == 1:
        return code.replace(" ", "").lower()     # "csye6200"
    return f"{code.replace(' ', '')} 这门课怎么样"  # CJK-adjacent, v3.1 regex case


# Queries that got clipped mid-thought (gemini-2.5-flash thinking tokens
# share the output budget; a tight cap truncates the visible text) end in
# function words / dangling punctuation — reject and move to the next course.
_DANGLING_RE = re.compile(
    r"(?:\b(?:of|for|the|and|or|on|to|with|a|an|in|如何|与|和)\s*$|[,、，:：]\s*$)",
    re.IGNORECASE,
)


def _looks_complete(q: str) -> bool:
    return 6 <= len(q) <= 140 and not _DANGLING_RE.search(q)


def _llm_query(prompt: str) -> str | None:
    """One Gemini call → single-line query text (None on any failure)."""
    from llm.gemini_client import GeminiError, generate_text  # noqa: PLC0415

    try:
        # 2048: gemini-2.5-flash spends "thinking" tokens from the same
        # budget — 200 visibly truncated ~1/3 of outputs on the first run.
        out = generate_text(prompt, temperature=0.8, max_output_tokens=2048)
    except GeminiError as e:
        print(f"   ! LLM failed: {e}")
        return None
    line = out.strip().splitlines()[0].strip().strip('"').strip()
    if not line or not _looks_complete(line):
        print(f"   ! dropped incomplete output: {line[:60]!r}")
        return None
    return line


def _medium_prompt(name: str, raw_text: str) -> str:
    return (
        "You are simulating a graduate student searching a university course "
        "catalog. Based on the course description below, write ONE natural "
        "search query (6-14 words, English) a student would type to find "
        "this course. CRITICAL: do NOT reuse the course title words; "
        "describe what they want to learn instead. Output ONLY the query.\n\n"
        f"Course title: {name}\nDescription: {raw_text[:600]}"
    )


def _complex_prompt(name: str, raw_text: str) -> str:
    return (
        "You are simulating a graduate student searching a university course "
        "catalog. Based on the course description below, write ONE natural "
        "search query that mixes a topic with a constraint or preference "
        "(e.g. workload, level, projects, prerequisites, career goal). "
        "8-18 words, English, do NOT reuse the exact course title. "
        "Output ONLY the query.\n\n"
        f"Course title: {name}\nDescription: {raw_text[:600]}"
    )


def _boundary_prompt(name: str, raw_text: str) -> str:
    return (
        "你在模拟一个东北大学(Northeastern)的中国研究生用中文搜索选课系统。"
        "根据下面的课程描述,写一条自然的中文搜索 query(8-20 个字,"
        "可以夹杂英文专业术语,但不要出现课程编号和完整课程名)。"
        "只输出 query 本身。\n\n"
        f"课程名: {name}\n描述: {raw_text[:600]}"
    )


def cli() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db-path", required=True)
    ap.add_argument("--base", default=str(PROJECT_ROOT / "eval" / "test_set.json"))
    ap.add_argument("--out", default=str(PROJECT_ROOT / "eval" / "test_set_v03.json"))
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--no-llm", action="store_true",
                    help="Skip Gemini categories (simple+adversarial only)")
    args = ap.parse_args()

    from db.connection import connect  # noqa: PLC0415

    base = json.loads(Path(args.base).read_text(encoding="utf-8"))
    queries: list[dict] = list(base["queries"])
    next_id = max(int(q["query_id"][1:]) for q in queries) + 1

    conn = connect(str(Path(args.db_path).expanduser()))
    try:
        # Disjoint samples per category (seed offsets keep them stable).
        simple_courses = _sample_courses(conn, n=18, seed=args.seed)
        used = {c["course_id"] for c in simple_courses}
        llm_pool = [
            c for c in _sample_courses(conn, n=80, seed=args.seed + 1)
            if c["course_id"] not in used
        ]

        def add(category: str, query: str, expected: list[str], rationale: str):
            nonlocal next_id
            queries.append({
                "query_id": f"q{next_id:03d}",
                "category": category,
                "query": query,
                "expected_course_ids": expected,
                "rationale": rationale,
            })
            next_id += 1

        # --- simple: code-format variants ---
        for i, c in enumerate(simple_courses):
            add(
                "simple",
                _code_variant(c["primary_code"], i % 3),
                [c["course_id"]],
                f"v0.3 generated: code-format variant of {c['primary_code']}",
            )
        print(f"=> simple: +{len(simple_courses)}")

        # --- LLM categories ---
        if not args.no_llm:
            specs = [
                ("medium", 18, _medium_prompt),
                ("complex", 12, _complex_prompt),
                ("boundary", 6, _boundary_prompt),
            ]
            pool_iter = iter(llm_pool)
            for category, target, prompt_fn in specs:
                made = 0
                while made < target:
                    try:
                        c = next(pool_iter)
                    except StopIteration:
                        print(f"   ! pool exhausted at {category} ({made}/{target})")
                        break
                    q = _llm_query(prompt_fn(c["primary_name"], c["raw_text"]))
                    if not q:
                        continue
                    # Guard: paraphrase must not leak the course code (that
                    # would silently turn a semantic test into an alias test).
                    if re.search(re.escape(c["primary_code"].replace(" ", "")),
                                 q.replace(" ", ""), re.IGNORECASE):
                        continue
                    add(
                        category, q, [c["course_id"]],
                        f"v0.3 generated: Gemini {category} paraphrase of "
                        f"{c['primary_code']} ({c['primary_name'][:40]})",
                    )
                    made += 1
                print(f"=> {category}: +{made}")

        # --- adversarial: fresh hand-written ---
        for q in NEW_ADVERSARIAL:
            add("adversarial", q, [],
                "v0.3 generated: fresh adversarial (disjoint from ADR-0018 "
                "calibration set wording)")
        print(f"=> adversarial: +{len(NEW_ADVERSARIAL)}")

        # --- validation: every expected id exists + indexed ---
        bad = []
        for q in queries:
            for cid in q["expected_course_ids"]:
                row = conn.execute(
                    "SELECT status FROM courses WHERE course_id = ?", (cid,)
                ).fetchone()
                if row is None or row["status"] != "indexed":
                    bad.append((q["query_id"], cid))
        if bad:
            print(f"ERROR: {len(bad)} expected ids not indexed: {bad[:5]}")
            return 1
    finally:
        conn.close()

    from collections import Counter
    dist = Counter(q["category"] for q in queries)
    out = {
        "_comment": (
            "Eval set v0.3 — v0.2's 42 queries verbatim + generated expansion "
            "(scripts/generate_test_set_v03.py, seed "
            f"{args.seed}). Generated ground truth is weak-label: "
            "expected = the source course the query was derived from. "
            "ADR-0015/0016/0017/0018 re-validation target."
        ),
        "version": "0.3",
        "category_distribution": dict(dist),
        "queries": queries,
    }
    Path(args.out).write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    print(f"\n=> wrote {args.out}: {len(queries)} queries {dict(dist)}")
    return 0


if __name__ == "__main__":
    sys.exit(cli())
