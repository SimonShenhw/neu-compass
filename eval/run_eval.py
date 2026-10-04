"""Recall@K + MRR evaluator over a query/expected-courses test set.

Reads eval/test_set.json, runs each query through a retriever-like
callable, computes per-query and aggregate metrics. Prints text report
and (optionally) writes JSON breakdown.

Decoupled from any specific retriever: caller supplies a `search_fn`
that takes a query string and returns an ordered list of course_ids.
That way we can eval:
  - alias-only path (normalize_query_to_course_ids)
  - vector-only path (Retriever.search ignoring filters)
  - hybrid path (Week 5)
without changing the eval harness.

Ragas integration (Faithfulness, Context Precision, Answer Relevance)
arrives Week 5; this file stays focused on retrieval metrics.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


@dataclass
class QueryResult:
    """One query's eval outcome."""

    query_id: str
    query: str
    expected: list[str]
    retrieved: list[str]
    recall_at_5: float
    reciprocal_rank: float
    k: int = 5
    capped_recall_at_k: float | None = None
    standard_recall_at_k: float | None = None

    @property
    def hit(self) -> bool:
        return (self.capped_recall_at_k if self.capped_recall_at_k is not None else self.recall_at_5) > 0


@dataclass
class EvalReport:
    """Aggregate eval result."""

    per_query: list[QueryResult] = field(default_factory=list)
    recall_at_5: float = 0.0
    mrr: float = 0.0
    queries_with_expected: int = 0  # excludes adversarial empty-expected queries
    k: int = 5
    capped_recall_at_k: float | None = None
    standard_recall_at_k: float | None = None
    negative_queries: int = 0
    correct_rejections: int = 0

    def to_dict(self) -> dict:
        return {
            "summary": {
                "total_queries": len(self.per_query),
                "queries_with_expected": self.queries_with_expected,
                "recall_at_5": round(self.recall_at_5, 4),
                "mrr": round(self.mrr, 4),
                "k": self.k,
                "capped_recall_at_k": self.capped_recall_at_k,
                "standard_recall_at_k": self.standard_recall_at_k,
                "quality_status": "positive_queries_evaluated" if self.queries_with_expected else "no_positive_queries",
                "negative_queries": self.negative_queries,
                "correct_rejections": self.correct_rejections,
                "false_positives": self.negative_queries - self.correct_rejections,
                "rejection_accuracy": self.correct_rejections / self.negative_queries if self.negative_queries else None,
                "metric_definitions": {
                    "recall_at_5": "legacy_capped_coverage_at_5",
                    "capped_recall_at_k": "unique_hits_at_k_over_min_label_count_k",
                    "standard_recall_at_k": "unique_hits_at_k_over_label_count",
                    "mrr": "first_relevant_rank_in_full_returned_list",
                },
            },
            "per_query": [
                {
                    "query_id": q.query_id,
                    "query": q.query,
                    "expected": q.expected,
                    "retrieved": q.retrieved,
                    "recall_at_5": round(q.recall_at_5, 4),
                    "reciprocal_rank": round(q.reciprocal_rank, 4),
                    "k": q.k,
                    "capped_recall_at_k": q.capped_recall_at_k,
                    "standard_recall_at_k": q.standard_recall_at_k,
                }
                for q in self.per_query
            ],
        }


def recall_at_k(retrieved: list[str], expected: list[str], k: int = 5) -> float:
    """Fraction of expected items present in top-k retrieved, with the
    denominator capped at k (the project's historical capped coverage,
    NOT standard recall or R-precision). Duplicate labels cannot add hits.

    The cap matters for multi-label ground truth (test_set v0.4+): a query
    with 8 relevant courses can show at most 5 in the top-5 — uncapped
    recall would top out at 0.625 through no fault of the system. For the
    single-label v0.2/v0.3 sets (|expected| ≤ 3 ≤ k) min() is a no-op, so
    historic numbers are unaffected.

    For empty-expected queries (adversarial: 'AAI 9999'), recall is undefined;
    we return 1.0 if retrieved is also empty (correct rejection), else 0.0.
    """
    if type(k) is not int or k < 1:
        raise ValueError('invalid_eval_k')
    expected = set(expected)
    if not expected:
        return 1.0 if not retrieved else 0.0
    top_k = set(retrieved[:k])
    hits = len(expected & top_k)
    return hits / min(len(expected), k)


def reciprocal_rank(retrieved: list[str], expected: list[str]) -> float:
    """1 / rank-of-first-relevant. 0 if no relevant item retrieved.

    For empty-expected queries, returns 1.0 if also empty retrieved else 0.0
    (consistent with recall_at_k semantics for adversarial cases).
    """
    if not expected:
        return 1.0 if not retrieved else 0.0
    expected_set = set(expected)
    for i, cid in enumerate(retrieved, start=1):
        if cid in expected_set:
            return 1.0 / i
    return 0.0


def validate_test_set(test_set: dict, *, k: int = 5) -> list[dict]:
    """Validate ALL labels before a callable can cause I/O or query writes."""
    if type(k) is not int or not 1 <= k <= 100:
        raise ValueError('invalid_eval_k')
    if not isinstance(test_set, dict) or not isinstance(test_set.get('queries'), list):
        raise ValueError('invalid_eval_queries')
    if len(test_set['queries']) > 10_000:
        raise ValueError('eval_query_count_budget')
    ids, entries = set(), []
    for entry in test_set['queries']:
        if not isinstance(entry, dict):
            raise ValueError('invalid_eval_entry')
        qid, query, labels = (entry.get(key) for key in ('query_id', 'query', 'expected_course_ids'))
        if (not isinstance(qid, str) or not qid.strip() or qid in ids
                or not isinstance(query, str) or not query.strip()
                or not isinstance(labels, list)
                or any(not isinstance(value, str) or not value.strip() for value in labels)):
            raise ValueError('invalid_eval_identity_or_labels')
        if len(labels) != len(set(labels)):
            raise ValueError('duplicate_eval_labels')
        ids.add(qid)
        entries.append({**entry, 'expected_course_ids': list(labels)})
    return entries


def run_eval(
    test_set: dict,
    search_fn: Callable[[str], list[str]],
    *,
    k: int = 5,
) -> EvalReport:
    """Run search_fn on every query, compute per-query + aggregate metrics."""
    entries = validate_test_set(test_set, k=k)
    report = EvalReport(k=k)
    for entry in entries:
        retrieved = search_fn(entry["query"])
        if (not isinstance(retrieved, list)
                or any(not isinstance(value, str) or not value.strip() for value in retrieved)
                or len(retrieved) != len(set(retrieved))):
            raise ValueError('invalid_eval_retrieved_ids')
        retrieved = list(retrieved)
        expected = entry['expected_course_ids']

        recall = recall_at_k(retrieved, expected, k=k)
        rr = reciprocal_rank(retrieved, expected)

        report.per_query.append(QueryResult(
            query_id=entry["query_id"],
            query=entry["query"],
            expected=expected,
            retrieved=retrieved,
            recall_at_5=recall_at_k(retrieved, expected, k=5),
            reciprocal_rank=rr,
            k=k, capped_recall_at_k=recall,
            standard_recall_at_k=len(set(retrieved[:k]) & set(expected)) / len(expected) if expected else None,
        ))

    # Aggregate. Adversarial empty-expected queries have a separate semantic
    # (correct rejection) so they shouldn't dilute recall over real lookups.
    real_queries = [q for q in report.per_query if q.expected]
    report.queries_with_expected = len(real_queries)

    if real_queries:
        report.recall_at_5 = statistics.mean(q.recall_at_5 for q in real_queries)
        report.mrr = statistics.mean(q.reciprocal_rank for q in real_queries)
        report.capped_recall_at_k = statistics.mean(q.capped_recall_at_k for q in real_queries)
        report.standard_recall_at_k = statistics.mean(q.standard_recall_at_k for q in real_queries)
    negatives = [q for q in report.per_query if not q.expected]
    report.negative_queries = len(negatives)
    report.correct_rejections = sum(not q.retrieved for q in negatives)

    return report


def render_text(report: EvalReport) -> str:
    lines = [
        "=" * 60,
        f"Legacy capped coverage@5: {report.recall_at_5:.3f}   "
        f"MRR: {report.mrr:.3f}   "
        f"({report.queries_with_expected}/{len(report.per_query)} queries with expected)",
        "=" * 60,
        f"Requested k={report.k}; capped coverage={report.capped_recall_at_k}; "
        f"standard recall={report.standard_recall_at_k}; "
        f"correct rejections={report.correct_rejections}/{report.negative_queries}",
    ]
    for q in report.per_query:
        marker = "✓" if q.hit else "✗"
        lines.append(
            f"{marker} {q.query_id} R@5={q.recall_at_5:.2f} "
            f"RR={q.reciprocal_rank:.2f} :: {q.query[:50]!r}"
        )
        if q.expected:
            lines.append(f"     expected: {q.expected}")
        if q.retrieved[:3]:
            lines.append(f"     top 3 :   {q.retrieved[:3]}")
    return "\n".join(lines)


def cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--test-set", default=str(PROJECT_ROOT / "eval" / "test_set.json"),
        help="Path to test_set.json",
    )
    parser.add_argument(
        "--mode",
        choices=["alias_only", "vector_only", "hybrid", "hybrid_with_alias"],
        default="alias_only",
        help=(
            "Which retrieval path to evaluate.\n"
            "  alias_only:        query_normalizer → AliasRepository.resolve only\n"
            "  vector_only:       FAISS + bge-m3 (no BM25)\n"
            "  hybrid:            BM25 + vector via RRF\n"
            "  hybrid_with_alias: alias-first, fall through to hybrid (production path)"
        ),
    )
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--out-json", default=None,
                        help="Optional path to write the per-query JSON breakdown")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument(
        "--rerank", action="store_true",
        help="Apply bge-reranker-v2-m3 cross-encoder on top of vector / hybrid "
             "candidates. No effect for alias_only mode. Adds ~30s model load "
             "+ ~50ms/query latency.",
    )
    parser.add_argument(
        "--rerank-pool", type=int, default=20,
        help="Number of candidates to ask the upstream retriever for before "
             "reranking. Larger = better recall, slower. Default: 20.",
    )
    parser.add_argument(
        "--with-rejection", action="store_true",
        help="Apply rerank+blend+reject path matching api/routes/search.py. "
             "Defaults mirror production: blend_alpha=0.4 (ADR-0015) / "
             "reject_threshold=0.05 (ADR-0016). Implies --rerank.",
    )
    parser.add_argument(
        "--blend-alpha", type=float, default=0.4,
        help="Z-score blend weight on RRF leg. ADR-0015 locks 0.4.",
    )
    parser.add_argument(
        "--reject-threshold", type=float, default=0.05,
        help="Raw reranker sigmoid floor below which the query is rejected. "
             "ADR-0016 locks 0.05 (production value in api/routes/search.py); "
             "the old 0.4 default here silently measured the wrong operating "
             "point.",
    )
    args = parser.parse_args()
    if args.with_rejection:
        args.rerank = True

    test_set = json.loads(Path(args.test_set).read_text(encoding="utf-8"))
    validate_test_set(test_set, k=args.k)  # Before config/model/DB setup.

    if args.db_path is None:
        from config import settings  # noqa: PLC0415
        db_path = settings.sqlite_path
        faiss_path = settings.faiss_index_path
    else:
        db_path = args.db_path
        faiss_path = None  # require explicit when db is overridden

    from db.alias_repository import AliasRepository  # noqa: PLC0415
    from db.connection import connect  # noqa: PLC0415
    from db.repository import CourseRepository  # noqa: PLC0415
    from rag.query_normalizer import normalize_query_to_course_ids  # noqa: PLC0415

    conn = connect(db_path)
    try:
        alias_repo = AliasRepository(conn)
        course_repo = CourseRepository(conn)

        if args.mode == "alias_only":
            search_fn = lambda q: normalize_query_to_course_ids(  # noqa: E731
                q, alias_repo=alias_repo,
            )
        elif args.mode in ("vector_only", "hybrid", "hybrid_with_alias"):
            from rag.embedder import BGEM3Embedder  # noqa: PLC0415
            from rag.hybrid import BM25Corpus, HybridRetriever  # noqa: PLC0415
            from rag.index import FaissIndex  # noqa: PLC0415
            from rag.retriever import Retriever, SearchHit  # noqa: PLC0415

            if faiss_path is None:
                from config import settings as _s  # noqa: PLC0415
                faiss_path = _s.faiss_index_path

            print(f"=> loading FAISS from {faiss_path}")
            index = FaissIndex.load(faiss_path)
            print(f"   index: {index.count} vectors")
            print("=> warming bge-m3 (first encode triggers ~70s model load) ...")
            embedder = BGEM3Embedder()
            embedder.encode(["warmup"])
            print("=> embedder ready")

            reranker = None
            fetch_text = None
            if args.rerank:
                from rag.reranker import (  # noqa: PLC0415
                    CrossEncoderReranker,
                    rerank_search_hits,
                )

                print("=> warming bge-reranker-v2-m3 (~30s) ...")
                reranker = CrossEncoderReranker()
                reranker.score("warmup", ["warmup"])
                print("=> reranker ready")

                def fetch_text(cid: str) -> str | None:  # type: ignore[no-redef]
                    row = conn.execute(
                        "SELECT raw_text FROM courses WHERE course_id = ?", (cid,)
                    ).fetchone()
                    return row["raw_text"] if row else None

            vector = Retriever(
                embedder=embedder, index=index,
                course_repo=course_repo, sqlite_conn=conn,
            )

            def _maybe_rerank(query: str, hits: list[SearchHit]) -> list[SearchHit]:
                if not args.rerank:
                    return hits[: args.k]
                if args.with_rejection:
                    from rag.reranker import (  # noqa: PLC0415
                        rerank_blend_with_rejection,
                    )
                    out, meta = rerank_blend_with_rejection(
                        query, hits, reranker,
                        fetch_text=fetch_text,
                        blend_alpha=args.blend_alpha,
                        reject_threshold=args.reject_threshold,
                        top_k=args.k,
                    )
                    return out  # [] when rejected — eval treats as correct on adversarial
                from rag.reranker import rerank_search_hits  # noqa: PLC0415
                return rerank_search_hits(
                    query, hits, reranker, fetch_text=fetch_text, top_k=args.k,
                )

            pool = args.rerank_pool if args.rerank else args.k

            if args.mode == "vector_only":
                def _search_vector(q: str) -> list[str]:
                    hits = vector.search(q, k=pool)
                    return [h.course.course_id for h in _maybe_rerank(q, hits)]
                search_fn = _search_vector
            else:  # hybrid or hybrid_with_alias
                bm25 = BM25Corpus.from_db(conn)
                print(f"   bm25 corpus: {bm25.count} docs")
                hybrid = HybridRetriever(
                    vector_retriever=vector,
                    bm25_corpus=bm25,
                    course_repo=course_repo,
                )

                if args.mode == "hybrid":
                    def _search_hybrid(q: str) -> list[str]:
                        hits = hybrid.search(q, k=pool)
                        return [h.course.course_id for h in _maybe_rerank(q, hits)]
                    search_fn = _search_hybrid
                else:  # hybrid_with_alias — production path
                    def _search_alias_then_hybrid(q: str) -> list[str]:
                        alias_ids = normalize_query_to_course_ids(
                            q, alias_repo=alias_repo,
                        )
                        if alias_ids:
                            return alias_ids
                        hits = hybrid.search(q, k=pool)
                        return [h.course.course_id for h in _maybe_rerank(q, hits)]
                    search_fn = _search_alias_then_hybrid
        else:
            raise ValueError(f"Unknown mode: {args.mode}")

        report = run_eval(test_set, search_fn, k=args.k)
    finally:
        conn.close()

    print(render_text(report))

    if args.out_json:
        Path(args.out_json).write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\nWrote per-query JSON: {args.out_json}")

    return 0


if __name__ == "__main__":
    sys.exit(cli())


__all__ = [
    "EvalReport",
    "QueryResult",
    "recall_at_k",
    "reciprocal_rank",
    "render_text",
    "run_eval",
    "validate_test_set",
]
