"""Quick repeatable RAG smoke test: load index + embedder, run targeted queries.

Reads the configured FAISS index + DB; runs a battery of queries with
known expected courses; prints a ranking table + top-1 accuracy.

Usage (after seed_synthetic_courses.py + rebuild_faiss.py):
    uv run python scripts/smoke_rag_query.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import settings  # noqa: E402
from db.connection import connect  # noqa: E402
from db.repository import CourseRepository  # noqa: E402
from rag.embedder import BGEM3Embedder  # noqa: E402
from rag.index import FaissIndex  # noqa: E402
from rag.retriever import Retriever  # noqa: E402

# (query, expected_top_course_code, rationale).
# expected=None means adversarial / unrelated; we just expect a low score.
TESTS: list[tuple[str, str | None, str]] = [
    ("graph algorithms BFS DFS shortest paths",        "CS 5800",   "pure algos vocab"),
    ("k-means clustering and dimensionality reduction", "DS 5230",   "unsupervised ML"),
    ("neural network training with backpropagation",    "DS 5220",   "supervised NN"),
    ("VC dimension PAC learning theory",                "CS 6140",   "stats learning theory"),
    ("Apache Spark ETL data pipelines",                 "INFO 6105", "data engineering"),
    ("convex optimization Lagrangian duality",          "MATH 7243", "math foundations"),
    ("AI fundamentals and search algorithms",           "AAI 6600",  "the seed course"),
    ("quantum cryptography seminar",                    None,        "adversarial / unrelated"),
]


def main() -> int:
    print("=> loading FAISS + embedder + DB")
    t0 = time.perf_counter()
    index = FaissIndex.load(settings.faiss_index_path)
    emb = BGEM3Embedder(device="cuda")
    emb.encode(["warmup"])  # force model into GPU
    conn = connect(settings.sqlite_path)
    retriever = Retriever(
        embedder=emb,
        index=index,
        course_repo=CourseRepository(conn),
        sqlite_conn=conn,
    )
    print(f"   ready in {time.perf_counter() - t0:.1f}s ({index.count} courses)")
    print()

    header = f"{'Query':<55} {'Expect':<10} {'#1':<10} {' ':<3} {'score':<8} {'top3'}"
    print(header)
    print("-" * 135)

    hit_count = 0
    real_queries = 0
    for q, expected, _rationale in TESTS:
        hits = retriever.search(q, k=3)
        top1 = hits[0].course.primary_code if hits else "—"
        top1_score = hits[0].score if hits else 0.0
        top3 = " > ".join(h.course.primary_code for h in hits) if hits else "—"
        correct = (expected is None) or (top1 == expected)
        if expected is not None:
            real_queries += 1
            if correct:
                hit_count += 1
        mark = "✓" if correct else "✗"
        print(f"  {q[:53]:<55} {str(expected):<10} {top1:<10} {mark}  {top1_score:.3f}   {top3}")

    print()
    if real_queries:
        print(f"Top-1 accuracy on real queries: {hit_count}/{real_queries} = {hit_count / real_queries:.0%}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
