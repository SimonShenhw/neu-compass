"""Reject-threshold ROC sweep — calibrate RERANKER_REJECT_THRESHOLD.

Smoke for PLAN v2.2 §3.4. Initial threshold (0.4) was specified before
empirical validation; full eval on test_set v0.2 showed the R@5 drop
from 0.621 (no rejection) to 0.529 (with rejection at 0.4) was driven
by **false rejections** of legitimate queries, not by adversarial wins.

This sweep loads the live stack once, runs every query once through
hybrid → reranker (no rejection), captures per-query max_sigmoid, then
computes:
  - real_recall_at_5(T)  — fraction of real queries that BOTH (a) had
    max_sigmoid ≥ T (not rejected) AND (b) hit on top-5
  - adv_rejection(T)     — fraction of adversarial queries with max < T

The Pareto frontier on (real_recall, adv_rejection) tells us the
operating point. Decision threshold goes into the ADR-0015 supplement
(or a new ADR if the change is large).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_THRESHOLDS = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50]


def cli() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--test-set", default=str(PROJECT_ROOT / "eval" / "test_set.json"))
    ap.add_argument(
        "--out-json",
        default=str(PROJECT_ROOT / "eval" / "reject_threshold_sweep.json"),
    )
    ap.add_argument("--rerank-pool", type=int, default=20)
    ap.add_argument("--blend-alpha", type=float, default=0.4)
    ap.add_argument(
        "--thresholds",
        default=",".join(str(t) for t in DEFAULT_THRESHOLDS),
    )
    ap.add_argument("--db-path", default=None)
    args = ap.parse_args()

    thresholds = [float(t) for t in args.thresholds.split(",")]

    from config import settings  # noqa: PLC0415
    db_path = args.db_path or settings.sqlite_path
    faiss_path = settings.faiss_index_path

    from db.alias_repository import AliasRepository  # noqa: PLC0415
    from db.connection import connect  # noqa: PLC0415
    from db.repository import CourseRepository  # noqa: PLC0415
    from rag.embedder import BGEM3Embedder  # noqa: PLC0415
    from rag.hybrid import BM25Corpus, HybridRetriever  # noqa: PLC0415
    from rag.index import FaissIndex  # noqa: PLC0415
    from rag.query_normalizer import normalize_query_to_course_ids  # noqa: PLC0415
    from rag.reranker import CrossEncoderReranker, zscore_blend  # noqa: PLC0415
    from rag.retriever import Retriever  # noqa: PLC0415

    print(f"=> loading FAISS from {faiss_path}")
    index = FaissIndex.load(faiss_path)
    print(f"   index: {index.count} vectors")

    print("=> warming bge-m3 (~70s on first run)")
    embedder = BGEM3Embedder()
    embedder.encode(["warmup"])
    print("=> embedder ready")

    print("=> warming bge-reranker-v2-m3 (~30s on first run)")
    reranker = CrossEncoderReranker()
    reranker.score("warmup", ["warmup"])
    print("=> reranker ready")

    test_set = json.loads(Path(args.test_set).read_text(encoding="utf-8"))

    conn = connect(db_path)
    try:
        alias_repo = AliasRepository(conn)
        course_repo = CourseRepository(conn)
        bm25 = BM25Corpus.from_db(conn)
        vector = Retriever(
            embedder=embedder, index=index,
            course_repo=course_repo, sqlite_conn=conn,
        )
        hybrid = HybridRetriever(
            vector_retriever=vector,
            bm25_corpus=bm25,
            course_repo=course_repo,
        )

        def fetch_text(cid: str) -> str | None:
            row = conn.execute(
                "SELECT raw_text FROM courses WHERE course_id = ?", (cid,)
            ).fetchone()
            return row["raw_text"] if row else None

        # Phase 1: per-query reranker scoring (no threshold gating yet).
        per_query: list[dict] = []
        for entry in test_set["queries"]:
            q = entry["query"]
            expected = entry.get("expected_course_ids", [])
            qid = entry["query_id"]

            alias_ids = normalize_query_to_course_ids(q, alias_repo=alias_repo)
            if alias_ids:
                # Alias path bypasses the reranker entirely — record as
                # always-accepted with sentinel max_sigmoid=1.0.
                top5 = alias_ids[:5]
                per_query.append({
                    "query_id": qid,
                    "expected": expected,
                    "matched_via": "alias",
                    "max_sigmoid": 1.0,
                    "top5_blended": top5,
                    "hit": any(c in top5 for c in expected) if expected else None,
                })
                continue

            hits = hybrid.search(q, k=args.rerank_pool)
            if not hits:
                per_query.append({
                    "query_id": qid,
                    "expected": expected,
                    "matched_via": "empty",
                    "max_sigmoid": 0.0,
                    "top5_blended": [],
                    "hit": False if expected else True,
                })
                continue

            texts = [fetch_text(h.course.course_id) or h.course.primary_name
                     for h in hits]
            rrf = [h.score for h in hits]
            sig = reranker.score(q, texts)
            blended = zscore_blend(rrf, sig, alpha=args.blend_alpha)
            order = sorted(range(len(hits)), key=lambda i: -blended[i])[:5]
            top5 = [hits[i].course.course_id for i in order]
            per_query.append({
                "query_id": qid,
                "expected": expected,
                "matched_via": "hybrid",
                "max_sigmoid": float(max(sig)),
                "top5_blended": top5,
                "hit": any(c in top5 for c in expected) if expected else None,
            })

        # Phase 2: derive metrics per threshold (no extra inference).
        real = [q for q in per_query if q["expected"]]
        adv = [q for q in per_query if not q["expected"]]

        rows: list[dict] = []
        for T in thresholds:
            real_kept = [q for q in real if q["max_sigmoid"] >= T]
            real_hits = [q for q in real_kept if q["hit"]]
            real_recall_at_5 = len(real_hits) / len(real) if real else 0.0
            real_kept_rate = len(real_kept) / len(real) if real else 0.0

            adv_rejected = [q for q in adv if q["max_sigmoid"] < T]
            adv_rejection_rate = len(adv_rejected) / len(adv) if adv else 0.0

            rows.append({
                "threshold": T,
                "real_recall_at_5": round(real_recall_at_5, 4),
                "real_kept_rate": round(real_kept_rate, 4),
                "real_false_rejections": len(real) - len(real_kept),
                "adv_rejection_rate": round(adv_rejection_rate, 4),
                "adv_rejections": len(adv_rejected),
                "n_real": len(real),
                "n_adv": len(adv),
            })
            print(
                f"   T={T:.2f}  R@5={real_recall_at_5:.4f}  "
                f"adv_rej={len(adv_rejected)}/{len(adv)}  "
                f"false_rej_real={len(real) - len(real_kept)}/{len(real)}"
            )
    finally:
        conn.close()

    output = {
        "test_set_version": test_set.get("version", "unknown"),
        "blend_alpha_locked": args.blend_alpha,
        "rerank_pool": args.rerank_pool,
        "n_queries": len(per_query),
        "n_real": len(real),
        "n_adv": len(adv),
        "thresholds_tested": thresholds,
        "max_sigmoid_per_query": [
            {"query_id": q["query_id"], "max_sigmoid": q["max_sigmoid"]}
            for q in per_query
        ],
        "results": rows,
    }
    Path(args.out_json).write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\n=> wrote {args.out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(cli())
