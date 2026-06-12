"""Build test_set v0.4 — multi-label ground truth via pooling + LLM judging.

The single-label problem (ADR-0023 / q108): generated queries carry ONE
expected course (the generation source), but a 6.5k-course catalog usually
has several genuinely relevant courses per query. The system returning a
different-but-correct course scores 0 — an eval false negative that both
understates quality (R@5 is a lower bound) and can veto good changes.

Pipeline (UMBRELA-flavored, adapted to zero-traffic conditions):
  1. POOL: for every non-adversarial query, union(current expected ids,
     live production top-10). Pooling over the deployed system mirrors
     TREC practice — judge what retrieval can actually surface.
  2. JUDGE: one Gemini call per query grades ALL its pooled candidates
     0-3 (UMBRELA scale) given the query + course name + description.
  3. ASSEMBLE: expected = {grade ≥ 2} ∪ {source course if grade ≥ 1}.
     A source course graded 0 means the GENERATED query itself is bad —
     the query is dropped and logged (eval hygiene, not system mercy).
     Adversarial queries keep expected=[] untouched (their semantics is
     "reject", not relevance).

Pair recall_at_k's min(|expected|, k) cap in eval/run_eval.py — without
it multi-label queries top out below 1.0 by construction.

Usage (PC WSL; needs the live API + GEMINI_API_KEY; ~100 judge calls):
  uv run python scripts/build_test_set_v04.py \
      --base-url http://100.72.36.13:8000 \
      --db-path ~/neu-compass-data/courses.db
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class Judgment(BaseModel):
    course_id: str
    grade: int = Field(ge=0, le=3)


class JudgmentList(BaseModel):
    items: list[Judgment]


JUDGE_PROMPT = """You are a relevance assessor for a university course-search \
engine (UMBRELA-style). A graduate student issued the search query below \
(possibly Chinese or mixed Chinese/English). Grade EACH candidate course:

3 = perfectly relevant: the course is exactly what the query asks for
2 = highly relevant: a student with this query would plausibly want this course
1 = related: shares topic vocabulary but doesn't serve the query's intent
0 = irrelevant

Grade on the course's CONTENT vs the query's INTENT — not on string overlap.
Return a grade for every candidate course_id given.

Query: {query}

Candidates:
{candidates}
"""


def cli() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--db-path", required=True)
    ap.add_argument("--test-set",
                    default=str(PROJECT_ROOT / "eval" / "test_set_v031.json"))
    ap.add_argument("--out",
                    default=str(PROJECT_ROOT / "eval" / "test_set_v04.json"))
    ap.add_argument("--pool-k", type=int, default=10)
    args = ap.parse_args()

    from db.connection import connect  # noqa: PLC0415
    from llm.gemini_client import GeminiError, generate_structured  # noqa: PLC0415

    base = json.loads(Path(args.test_set).read_text(encoding="utf-8"))
    conn = connect(str(Path(args.db_path).expanduser()))

    def course_blurb(cid: str) -> str | None:
        r = conn.execute(
            "SELECT primary_code, primary_name, COALESCE(raw_text,'') AS t "
            "FROM courses WHERE course_id = ?", (cid,),
        ).fetchone()
        if r is None:
            return None
        return f"{r['primary_code']} {r['primary_name']}: {r['t'][:280]}"

    # === 1. POOL via live production ===
    judged_queries = [
        q for q in base["queries"] if q.get("expected_course_ids")
    ]
    print(f"=> pooling top-{args.pool_k} for {len(judged_queries)} queries "
          f"({len(base['queries']) - len(judged_queries)} adversarial untouched)")
    pools: dict[str, list[str]] = {}
    with httpx.Client(base_url=args.base_url, timeout=120) as client:
        for i, q in enumerate(judged_queries):
            r = client.post("/search", json={"query": q["query"], "k": args.pool_k})
            r.raise_for_status()
            hits = [h["course_id"] for h in r.json().get("results", [])]
            pool = list(dict.fromkeys(q["expected_course_ids"] + hits))
            pools[q["query_id"]] = pool
            if (i + 1) % 25 == 0:
                print(f"   pooled {i + 1}/{len(judged_queries)}")

    # === 2. JUDGE (one listwise call per query, 4 workers) ===
    def judge(q: dict) -> tuple[str, dict[str, int] | None]:
        pool = pools[q["query_id"]]
        lines = []
        for cid in pool:
            blurb = course_blurb(cid)
            if blurb:
                lines.append(f"- course_id: {cid} | {blurb}")
        prompt = JUDGE_PROMPT.format(query=q["query"], candidates="\n".join(lines))
        try:
            out = generate_structured(
                prompt, schema=JudgmentList, temperature=0.0,
            )
        except GeminiError as e:
            print(f"   ! judge failed {q['query_id']}: {str(e)[:80]}")
            return q["query_id"], None
        return q["query_id"], {
            j.course_id: j.grade for j in out.items if j.course_id in pool
        }

    grades: dict[str, dict[str, int]] = {}
    with ThreadPoolExecutor(max_workers=4) as pool_ex:
        futs = [pool_ex.submit(judge, q) for q in judged_queries]
        for n, fut in enumerate(as_completed(futs)):
            qid, g = fut.result()
            if g is not None:
                grades[qid] = g
            if (n + 1) % 25 == 0:
                print(f"   judged {n + 1}/{len(judged_queries)}")

    # === 3. ASSEMBLE ===
    out_queries, dropped, disagreements = [], [], []
    for q in base["queries"]:
        if not q.get("expected_course_ids"):
            out_queries.append(q)  # adversarial verbatim
            continue
        g = grades.get(q["query_id"])
        if g is None:
            out_queries.append(q)  # judge failed → keep single label
            continue
        source = q["expected_course_ids"][0]
        relevant = {cid for cid, grade in g.items() if grade >= 2}
        src_grade = g.get(source)
        if src_grade is not None and src_grade == 0:
            dropped.append((q["query_id"], q["query"]))
            continue  # malformed generated query — out of the eval set
        if src_grade is not None and src_grade < 2:
            disagreements.append((q["query_id"], src_grade))
            relevant.add(source)  # keep weak label at grade 1 (benefit of doubt)
        relevant.add(source)
        new_q = dict(q)
        new_q["expected_course_ids"] = sorted(relevant)
        new_q["judge_grades"] = g
        out_queries.append(new_q)

    sizes = [len(q["expected_course_ids"]) for q in out_queries
             if q.get("expected_course_ids")]
    doc = {
        "_comment": base["_comment"] + " | v0.4: multi-label ground truth via "
        "production pooling + Gemini UMBRELA-style judging "
        "(scripts/build_test_set_v04.py). recall@k denominator capped at k.",
        "version": "0.4",
        "queries": out_queries,
    }
    Path(args.out).write_text(
        json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    print(f"\n=> wrote {args.out}: {len(out_queries)} queries")
    print(f"   labels/query: mean={sum(sizes)/len(sizes):.2f} max={max(sizes)}")
    print(f"   dropped (source graded 0): {len(dropped)} -> {dropped[:5]}")
    print(f"   source graded 1 (kept, flagged): {len(disagreements)}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(cli())
