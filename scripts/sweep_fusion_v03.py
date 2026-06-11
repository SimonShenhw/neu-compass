"""Fusion sweep on test_set v0.3 — RRF vs convex combination (ADR-0022).

The ADR-0015 α=0.4 lock and the RRF choice both predate test_set v0.3
(n=104) and the ADR-0020 vocabulary layer. This sweep settles, offline
against the production stack (run it in the NAS container):

  - fusion: RRF(k=60) baseline vs convex min-max combination at
    weight_vec ∈ {0.3..0.7}  (Bruch TOIS'23: tuned CC beats RRF)
  - blend α ∈ {0.2, 0.4, 0.6} re-checked per fusion config

Scope discipline: alias-resolvable queries are EXCLUDED (they bypass
fusion entirely → config-invariant noise), adversarial (empty-expected)
excluded (gate behavior isn't simulated here). The winner gets verified
end-to-end via scripts/eval_via_api.py after deploy — this sweep only
ranks configs relative to each other.

Reranker cost is amortized with a (query, course_id) → sigmoid cache:
pools overlap heavily across fusion configs, so the cross-encoder runs
roughly once per unique pair instead of once per config.

Run (NAS):
  docker run --rm -v /volume1/docker/neu-compass/runtime-data:/data \
    --device /dev/dri --group-add 44 --group-add 105 \
    --env-file /volume1/docker/neu-compass/.env \
    -e SQLITE_PATH=/data/courses.db -e FAISS_INDEX_PATH=/data/faiss_index \
    -e INFERENCE_BACKEND=openvino -e OPENVINO_MODEL_DIR=/data/openvino_int8 \
    -e OPENVINO_DEVICE=GPU -e OPENVINO_CACHE_DIR=/data/openvino_cache \
    neu-compass:latest python scripts/sweep_fusion_v03.py \
      --test-set /data/test_set_v03.json --out /data/fusion_sweep.json
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

FUSION_CONFIGS: list[tuple[str, float]] = [
    ("rrf", 0.0),
    ("convex", 0.3),
    ("convex", 0.4),
    ("convex", 0.5),
    ("convex", 0.6),
    ("convex", 0.7),
]
ALPHAS = [0.2, 0.4, 0.6]
POOL = 10  # production RERANK_POOL_SIZE (ADR-0017)
K = 5


def _recall(retrieved: list[str], expected: list[str]) -> float:
    top = set(retrieved[:K])
    return sum(1 for e in expected if e in top) / len(expected)


def _rr(retrieved: list[str], expected: list[str]) -> float:
    exp = set(expected)
    for i, cid in enumerate(retrieved, 1):
        if cid in exp:
            return 1.0 / i
    return 0.0


def cli() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--test-set", required=True)
    ap.add_argument("--out", default="/data/fusion_sweep.json")
    args = ap.parse_args()

    import structlog  # noqa: PLC0415

    from api.main import _build_inference_stack  # noqa: PLC0415
    from config import settings  # noqa: PLC0415
    from db.alias_repository import AliasRepository  # noqa: PLC0415
    from db.connection import connect  # noqa: PLC0415
    from db.repository import CourseRepository  # noqa: PLC0415
    from rag.acronyms import expand_query  # noqa: PLC0415
    from rag.hybrid import BM25Corpus, HybridRetriever  # noqa: PLC0415
    from rag.index import FaissIndex  # noqa: PLC0415
    from rag.query_normalizer import normalize_query_to_course_ids  # noqa: PLC0415
    from rag.reranker import zscore_blend  # noqa: PLC0415
    from rag.retriever import Retriever  # noqa: PLC0415

    embedder, reranker = _build_inference_stack(structlog.get_logger("sweep"))
    if reranker is None:
        print("ERROR: reranker required for this sweep")
        return 1

    index = FaissIndex.load(settings.faiss_index_path)
    conn = connect(settings.sqlite_path)
    test_set = json.loads(Path(args.test_set).read_text(encoding="utf-8"))
    try:
        alias_repo = AliasRepository(conn)
        course_repo = CourseRepository(conn)
        bm25 = BM25Corpus.from_db(conn)
        vector = Retriever(
            embedder=embedder, index=index,
            course_repo=course_repo, sqlite_conn=conn,
        )

        # Fusion-sensitive answerable queries only.
        queries = [
            q for q in test_set["queries"]
            if q.get("expected_course_ids")
            and not normalize_query_to_course_ids(q["query"], alias_repo=alias_repo)
        ]
        print(f"=> {len(queries)} fusion-sensitive queries "
              f"(of {len(test_set['queries'])} total)")

        sigmoid_cache: dict[tuple[str, str], float] = {}

        def sigmoids_for(query: str, course_ids: list[str]) -> list[float]:
            missing = [c for c in course_ids if (query, c) not in sigmoid_cache]
            if missing:
                texts = []
                for cid in missing:
                    r = conn.execute(
                        "SELECT COALESCE(raw_text,'') AS t FROM courses "
                        "WHERE course_id=?", (cid,),
                    ).fetchone()
                    texts.append(r["t"] if r and r["t"] else cid)
                for cid, s in zip(missing, reranker.score(query, texts)):
                    sigmoid_cache[(query, cid)] = float(s)
            return [sigmoid_cache[(query, c)] for c in course_ids]

        results = []
        for mode, weight in FUSION_CONFIGS:
            hybrid = HybridRetriever(
                vector_retriever=vector, bm25_corpus=bm25,
                course_repo=course_repo, query_expander=expand_query,
                fusion_mode=mode, fusion_weight=weight,
            )
            # Per query: ONE retrieval + sigmoid lookup, then re-blend per α.
            per_alpha: dict[float, list[tuple[float, float]]] = {
                a: [] for a in ALPHAS
            }
            for q in queries:
                hits = hybrid.search(q["query"], k=POOL)
                if not hits:
                    for a in ALPHAS:
                        per_alpha[a].append((0.0, 0.0))
                    continue
                cids = [h.course.course_id for h in hits]
                fused_scores = [h.score for h in hits]
                sigs = sigmoids_for(q["query"], cids)
                for a in ALPHAS:
                    blended = zscore_blend(fused_scores, sigs, alpha=a)
                    order = sorted(
                        range(len(blended)), key=lambda i: -blended[i],
                    )[:K]
                    retrieved = [cids[i] for i in order]
                    exp = q["expected_course_ids"]
                    per_alpha[a].append((_recall(retrieved, exp), _rr(retrieved, exp)))

            for a in ALPHAS:
                rows = per_alpha[a]
                r5 = sum(r for r, _ in rows) / len(rows)
                mrr = sum(m for _, m in rows) / len(rows)
                results.append({
                    "fusion": mode, "weight_vec": weight, "alpha": a,
                    "recall_at_5": round(r5, 4), "mrr": round(mrr, 4),
                })
                print(f"   {mode:6s} w={weight:.1f} α={a:.1f}: "
                      f"R@5={r5:.4f} MRR={mrr:.4f}")
    finally:
        conn.close()

    best = max(results, key=lambda r: (r["recall_at_5"], r["mrr"]))
    out = {"n_queries": len(queries), "results": results, "best": best}
    Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\n=> best: {best}")
    print(f"=> wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(cli())
