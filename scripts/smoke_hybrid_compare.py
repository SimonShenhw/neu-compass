"""Compare vector-only vs hybrid (BM25+vector RRF) retrieval on the
existing seeded corpus. Validates whether the empirical 0.485 > 0.463
inversion (docs/rag_smoke_results.md §6) is fixed by hybrid.

Run AFTER seed_synthetic_courses + load_slang_dict + rebuild_faiss.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import settings  # noqa: E402
from db.connection import connect  # noqa: E402
from db.repository import CourseRepository  # noqa: E402
from rag.embedder import BGEM3Embedder  # noqa: E402
from rag.hybrid import BM25Corpus, HybridRetriever  # noqa: E402
from rag.index import FaissIndex  # noqa: E402
from rag.retriever import Retriever  # noqa: E402

# Same battery as smoke_rag_query, plus more adversarial cases
TESTS: list[tuple[str, str | None]] = [
    ("graph algorithms BFS DFS shortest paths",        "CS 5800"),
    ("k-means clustering and dimensionality reduction", "DS 5230"),
    ("neural network training with backpropagation",    "DS 5220"),
    ("VC dimension PAC learning theory",                "CS 6140"),
    ("Apache Spark ETL data pipelines",                 "INFO 6105"),
    ("convex optimization Lagrangian duality",          "MATH 7243"),
    ("AI fundamentals and search algorithms",           "AAI 6600"),
    # Adversarial: should NOT match strongly
    ("quantum cryptography seminar",                    None),
    ("ancient roman history",                           None),
    ("woodworking and joinery",                         None),
]


def main() -> int:
    print("=> loading components")
    index = FaissIndex.load(settings.faiss_index_path)
    emb = BGEM3Embedder(device="cuda")
    emb.encode(["warmup"])
    conn = connect(settings.sqlite_path)
    course_repo = CourseRepository(conn)

    vector_only = Retriever(
        embedder=emb, index=index,
        course_repo=course_repo, sqlite_conn=conn,
    )
    bm25 = BM25Corpus.from_db(conn)
    hybrid = HybridRetriever(
        vector_retriever=vector_only,
        bm25_corpus=bm25,
        course_repo=course_repo,
    )
    print(f"   vector index: {index.count} docs")
    print(f"   bm25 corpus:  {bm25.count} docs")
    print()

    print(f"{'Query':<55} {'Expect':<11} {'V-#1':<10} {'V-score':<8} {'H-#1':<10} {'H-score':<8}")
    print("-" * 110)

    v_correct = 0
    h_correct = 0
    real_count = 0

    # Track adversarial-vs-real score gap for both methods
    v_scores_real: list[float] = []
    v_scores_adv: list[float] = []
    h_scores_real: list[float] = []
    h_scores_adv: list[float] = []

    for q, expected in TESTS:
        v_hits = vector_only.search(q, k=1)
        h_hits = hybrid.search(q, k=1)

        v_top = v_hits[0].course.primary_code if v_hits else "—"
        v_score = v_hits[0].score if v_hits else 0.0
        h_top = h_hits[0].course.primary_code if h_hits else "—"
        h_score = h_hits[0].score if h_hits else 0.0

        v_mark = "✓" if v_top == expected else " "
        h_mark = "✓" if h_top == expected else " "

        if expected is not None:
            real_count += 1
            v_correct += int(v_top == expected)
            h_correct += int(h_top == expected)
            v_scores_real.append(v_score)
            h_scores_real.append(h_score)
        else:
            v_scores_adv.append(v_score)
            h_scores_adv.append(h_score)

        print(
            f"  {q[:53]:<55} {str(expected):<11} "
            f"{v_top:<7} {v_mark}  {v_score:.3f}   "
            f"{h_top:<7} {h_mark}  {h_score:.3f}"
        )

    print()
    print(f"Top-1 accuracy on real queries: vector {v_correct}/{real_count} | hybrid {h_correct}/{real_count}")

    if v_scores_real and v_scores_adv:
        v_real_min = min(v_scores_real)
        v_adv_max = max(v_scores_adv)
        h_real_min = min(h_scores_real)
        h_adv_max = max(h_scores_adv)
        print()
        print("Score-gap analysis (positive = real beats adversarial; ≤0 = the kind of inversion we hit before):")
        print(f"  vector: real-min {v_real_min:.3f} - adv-max {v_adv_max:.3f} = {v_real_min - v_adv_max:+.3f}")
        print(f"  hybrid: real-min {h_real_min:.3f} - adv-max {h_adv_max:.3f} = {h_real_min - h_adv_max:+.3f}")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
