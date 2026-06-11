"""α grid search for Z-score blending — PLAN v2.2 §3.5 / KPI 4.

Sweeps `blend_alpha` over a grid, runs the same eval as run_eval.py
(mode=hybrid_with_alias + rerank), and writes per-α R@5, MRR, per-category
recall, and p50/p95 latency to JSON. Output feeds ADR-0015's α decision.

One-pass design (mirrors sweep_reject_threshold.py): retrieval + reranker
sigmoids don't depend on α — only the blend does. Each query pays the
embedder + reranker cost ONCE; per-α evaluation just re-blends the cached
scores. A 9-α sweep therefore costs ~1/9 of the old per-α reruns. The
reported p50/p95 latency is the α-invariant retrieval+rerank cost (identical
across α rows by construction).

Decision rule (v2.2 §3.5):
  1. Prefer Pareto-improving α: R@5 ≥ 0.636 AND MRR ≥ 0.603 (best-of-both
     baselines from rerank.json and hybrid_with_alias.json respectively).
  2. If none, fall back to: max MRR subject to R@5 ≥ 0.620.
  3. If none, max MRR unconstrained — flag as compromise in winner reason.

Caveat: n=42 queries in test_set v0.2 is statistically thin. Week 8 §4
re-sweep on test_set v0.3 (target 100) is mandatory; v2.2 acknowledges
this and ADR-0015 will get a Week 8 supplement.

Usage (WSL, ~2 min wall-clock cold):
    uv run python eval/sweep_blend_alpha.py
    uv run python eval/sweep_blend_alpha.py --alphas 0.3,0.5,0.7
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from eval.run_eval import run_eval  # noqa: E402

DEFAULT_ALPHAS = [0.0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0]

# Acceptance thresholds from PLAN v2.2 §3.5.
PARETO_R5 = 0.636   # rerank-only baseline R@5
PARETO_MRR = 0.603  # hybrid_with_alias baseline MRR
SOFT_R5_FLOOR = 0.620  # fallback floor if no Pareto-improvement


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = min(len(sorted_vals) - 1, int(len(sorted_vals) * pct))
    return sorted_vals[idx]


def cli() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--test-set",
        default=str(PROJECT_ROOT / "eval" / "test_set.json"),
        help="Path to test_set.json (default: eval/test_set.json)",
    )
    ap.add_argument(
        "--out-json",
        default=str(PROJECT_ROOT / "eval" / "blend_sweep_results.json"),
        help="Where to write the sweep results JSON",
    )
    ap.add_argument(
        "--rerank-pool",
        type=int,
        default=20,
        help="How many candidates hybrid returns before blending (default: 20)",
    )
    ap.add_argument(
        "--alphas",
        default=",".join(str(a) for a in DEFAULT_ALPHAS),
        help="Comma-separated α values to sweep",
    )
    ap.add_argument("--db-path", default=None, help="Override config.settings.sqlite_path")
    args = ap.parse_args()

    alphas = [float(a) for a in args.alphas.split(",")]

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
    category_map = {
        q["query_id"]: q.get("category", "uncategorized")
        for q in test_set["queries"]
    }

    conn = connect(db_path)
    try:
        alias_repo = AliasRepository(conn)
        course_repo = CourseRepository(conn)
        bm25 = BM25Corpus.from_db(conn)
        print(f"   bm25 corpus: {bm25.count} docs")
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

        # α-invariant per-query cache: either the alias short-circuit or
        # (course_ids, rrf_scores, rerank_sigmoids) from ONE retrieval +
        # reranker pass. Latency is recorded here — pass 1 only — because
        # re-blending cached scores is microseconds.
        query_cache: dict[str, dict] = {}
        latencies_ms: list[float] = []

        def expensive_pass(q: str) -> dict:
            cached = query_cache.get(q)
            if cached is not None:
                return cached
            t0 = time.perf_counter()
            alias_ids = normalize_query_to_course_ids(q, alias_repo=alias_repo)
            if alias_ids:
                entry: dict = {"alias_ids": alias_ids}
            else:
                hits = hybrid.search(q, k=args.rerank_pool)
                texts = [
                    fetch_text(h.course.course_id) or h.course.primary_name
                    for h in hits
                ]
                entry = {
                    "course_ids": [h.course.course_id for h in hits],
                    "rrf_scores": [h.score for h in hits],
                    "rerank_scores": reranker.score(q, texts) if hits else [],
                }
            latencies_ms.append((time.perf_counter() - t0) * 1000)
            query_cache[q] = entry
            return entry

        results_by_alpha: list[dict] = []

        for alpha in alphas:
            print(f"\n=> α = {alpha}")

            def search_fn(q: str, _alpha: float = alpha) -> list[str]:
                entry = expensive_pass(q)
                if "alias_ids" in entry:
                    return entry["alias_ids"]
                if not entry["course_ids"]:
                    return []
                blended = zscore_blend(
                    entry["rrf_scores"], entry["rerank_scores"], alpha=_alpha,
                )
                order = sorted(range(len(blended)), key=lambda i: -blended[i])[:5]
                return [entry["course_ids"][i] for i in order]

            report = run_eval(test_set, search_fn, k=5)

            cat_results: dict[str, list[float]] = defaultdict(list)
            for q in report.per_query:
                cat = category_map.get(q.query_id, "uncategorized")
                if q.expected:
                    cat_results[cat].append(q.recall_at_5)
            cat_recall = {
                cat: round(statistics.mean(vals), 4) if vals else None
                for cat, vals in cat_results.items()
            }

            sorted_lat = sorted(latencies_ms)
            p50 = _percentile(sorted_lat, 0.50)
            p95 = _percentile(sorted_lat, 0.95)

            print(
                f"   R@5={report.recall_at_5:.4f}  "
                f"MRR={report.mrr:.4f}  "
                f"p50={p50:.1f}ms p95={p95:.1f}ms"
            )

            results_by_alpha.append({
                "alpha": alpha,
                "recall_at_5": round(report.recall_at_5, 4),
                "mrr": round(report.mrr, 4),
                "category_recall_at_5": cat_recall,
                "p50_ms": round(p50, 1),
                "p95_ms": round(p95, 1),
                "n_queries_with_expected": report.queries_with_expected,
            })
    finally:
        conn.close()

    pareto = [
        r for r in results_by_alpha
        if r["recall_at_5"] >= PARETO_R5 and r["mrr"] >= PARETO_MRR
    ]
    if pareto:
        winner = max(pareto, key=lambda r: (r["mrr"], r["recall_at_5"]))
        decision_kind = "pareto"
        decision_note = (
            f"Pareto-improvement found: α={winner['alpha']} "
            f"(R@5={winner['recall_at_5']} ≥ {PARETO_R5}, "
            f"MRR={winner['mrr']} ≥ {PARETO_MRR})"
        )
    else:
        soft = [r for r in results_by_alpha if r["recall_at_5"] >= SOFT_R5_FLOOR]
        if soft:
            winner = max(soft, key=lambda r: r["mrr"])
            decision_kind = "soft_fallback"
            decision_note = (
                f"No Pareto-improvement; soft fallback "
                f"(R@5 ≥ {SOFT_R5_FLOOR}, max MRR): α={winner['alpha']}"
            )
        else:
            winner = max(results_by_alpha, key=lambda r: r["mrr"])
            decision_kind = "compromise"
            decision_note = (
                f"All α below R@5={SOFT_R5_FLOOR} floor; "
                f"compromise pick (max MRR unconstrained): α={winner['alpha']}"
            )

    output = {
        "test_set_version": test_set.get("version", "unknown"),
        "n_queries": len(test_set["queries"]),
        "n_queries_with_expected": (
            results_by_alpha[0]["n_queries_with_expected"]
            if results_by_alpha else 0
        ),
        "rerank_pool": args.rerank_pool,
        "alphas_tested": alphas,
        "baselines": {
            "alpha_1.0_pure_rrf_target": {
                "recall_at_5": 0.601, "mrr": 0.603,
                "source": "eval hybrid_with_alias on test_set v0.2",
            },
            "alpha_0.0_pure_rerank_target": {
                "recall_at_5": 0.636, "mrr": 0.545,
                "source": "eval hybrid_with_alias --rerank on test_set v0.2",
            },
        },
        "thresholds": {
            "pareto_r5": PARETO_R5,
            "pareto_mrr": PARETO_MRR,
            "soft_r5_floor": SOFT_R5_FLOOR,
        },
        "results": results_by_alpha,
        "decision": {
            "kind": decision_kind,
            "note": decision_note,
            "winner": winner,
        },
    }

    Path(args.out_json).write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\n=> wrote {args.out_json}")
    print(f"=> {decision_note}")
    print(
        f"=> winner: α={winner['alpha']}  "
        f"R@5={winner['recall_at_5']:.4f}  MRR={winner['mrr']:.4f}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(cli())
