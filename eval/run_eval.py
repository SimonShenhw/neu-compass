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

    @property
    def hit(self) -> bool:
        return self.recall_at_5 > 0


@dataclass
class EvalReport:
    """Aggregate eval result."""

    per_query: list[QueryResult] = field(default_factory=list)
    recall_at_5: float = 0.0
    mrr: float = 0.0
    queries_with_expected: int = 0  # excludes adversarial empty-expected queries

    def to_dict(self) -> dict:
        return {
            "summary": {
                "total_queries": len(self.per_query),
                "queries_with_expected": self.queries_with_expected,
                "recall_at_5": round(self.recall_at_5, 4),
                "mrr": round(self.mrr, 4),
            },
            "per_query": [
                {
                    "query_id": q.query_id,
                    "query": q.query,
                    "expected": q.expected,
                    "retrieved": q.retrieved,
                    "recall_at_5": round(q.recall_at_5, 4),
                    "reciprocal_rank": round(q.reciprocal_rank, 4),
                }
                for q in self.per_query
            ],
        }


def recall_at_k(retrieved: list[str], expected: list[str], k: int = 5) -> float:
    """Fraction of expected items present in top-k retrieved.

    For empty-expected queries (adversarial: 'AAI 9999'), recall is undefined;
    we return 1.0 if retrieved is also empty (correct rejection), else 0.0.
    """
    if not expected:
        return 1.0 if not retrieved else 0.0
    top_k = set(retrieved[:k])
    hits = sum(1 for e in expected if e in top_k)
    return hits / len(expected)


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


def run_eval(
    test_set: dict,
    search_fn: Callable[[str], list[str]],
    *,
    k: int = 5,
) -> EvalReport:
    """Run search_fn on every query, compute per-query + aggregate metrics."""
    report = EvalReport()
    for entry in test_set["queries"]:
        retrieved = search_fn(entry["query"])
        expected = entry.get("expected_course_ids", [])

        recall = recall_at_k(retrieved, expected, k=k)
        rr = reciprocal_rank(retrieved, expected)

        report.per_query.append(QueryResult(
            query_id=entry["query_id"],
            query=entry["query"],
            expected=expected,
            retrieved=retrieved,
            recall_at_5=recall,
            reciprocal_rank=rr,
        ))

    # Aggregate. Adversarial empty-expected queries have a separate semantic
    # (correct rejection) so they shouldn't dilute recall over real lookups.
    real_queries = [q for q in report.per_query if q.expected]
    report.queries_with_expected = len(real_queries)

    if real_queries:
        report.recall_at_5 = statistics.mean(q.recall_at_5 for q in real_queries)
        report.mrr = statistics.mean(q.reciprocal_rank for q in real_queries)

    return report


def render_text(report: EvalReport) -> str:
    lines = [
        "=" * 60,
        f"Recall@5: {report.recall_at_5:.3f}   "
        f"MRR: {report.mrr:.3f}   "
        f"({report.queries_with_expected}/{len(report.per_query)} queries with expected)",
        "=" * 60,
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
        "--mode", choices=["alias_only"], default="alias_only",
        help="Which retrieval path to evaluate. Currently only alias_only "
             "(others added when they exist).",
    )
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--out-json", default=None,
                        help="Optional path to write the per-query JSON breakdown")
    parser.add_argument("--k", type=int, default=5)
    args = parser.parse_args()

    test_set = json.loads(Path(args.test_set).read_text(encoding="utf-8"))

    if args.mode == "alias_only":
        from db.alias_repository import AliasRepository  # noqa: PLC0415
        from db.connection import connect  # noqa: PLC0415
        from rag.query_normalizer import normalize_query_to_course_ids  # noqa: PLC0415

        if args.db_path is None:
            from config import settings  # noqa: PLC0415
            db_path = settings.sqlite_path
        else:
            db_path = args.db_path

        conn = connect(db_path)
        try:
            alias_repo = AliasRepository(conn)
            search_fn = lambda q: normalize_query_to_course_ids(q, alias_repo=alias_repo)  # noqa: E731
            report = run_eval(test_set, search_fn, k=args.k)
        finally:
            conn.close()
    else:
        raise ValueError(f"Unknown mode: {args.mode}")

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
]
