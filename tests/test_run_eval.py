"""Tests for eval/run_eval — pure metric computations + harness driving."""

from __future__ import annotations

from eval.run_eval import (
    EvalReport,
    QueryResult,
    recall_at_k,
    reciprocal_rank,
    render_text,
    run_eval,
)


# === recall_at_k ===

def test_recall_full_hit() -> None:
    assert recall_at_k(["a", "b", "c"], ["a"], k=5) == 1.0


def test_recall_partial_hit() -> None:
    assert recall_at_k(["a", "b"], ["a", "x"], k=5) == 0.5


def test_recall_no_hit() -> None:
    assert recall_at_k(["x", "y"], ["a"], k=5) == 0.0


def test_recall_respects_k() -> None:
    """Item present at rank 6 should NOT count toward Recall@5."""
    retrieved = ["x"] * 5 + ["target"]
    assert recall_at_k(retrieved, ["target"], k=5) == 0.0
    assert recall_at_k(retrieved, ["target"], k=10) == 1.0


def test_recall_empty_expected_correct_rejection() -> None:
    """Adversarial query: expected=[], retrieved=[] -> 1.0 (correct rejection)."""
    assert recall_at_k([], [], k=5) == 1.0


def test_recall_empty_expected_false_positive() -> None:
    """Adversarial: expected=[], but retriever returned something -> 0.0."""
    assert recall_at_k(["something"], [], k=5) == 0.0


# === reciprocal_rank ===

def test_rr_first_position() -> None:
    assert reciprocal_rank(["target", "x"], ["target"]) == 1.0


def test_rr_second_position() -> None:
    assert reciprocal_rank(["x", "target"], ["target"]) == 0.5


def test_rr_no_hit() -> None:
    assert reciprocal_rank(["x", "y"], ["target"]) == 0.0


def test_rr_first_relevant_wins() -> None:
    """If multiple expected items, RR = 1/rank of FIRST relevant one."""
    assert reciprocal_rank(["b", "a", "c"], ["a", "c"]) == 0.5


def test_rr_empty_expected_correct() -> None:
    assert reciprocal_rank([], []) == 1.0


def test_rr_empty_expected_false_positive() -> None:
    assert reciprocal_rank(["x"], []) == 0.0


# === run_eval harness ===

def test_run_eval_aggregate() -> None:
    """search_fn is a stub returning hardcoded results per query."""
    test_set = {
        "queries": [
            {
                "query_id": "q1",
                "query": "AAI 6600",
                "expected_course_ids": ["c-aai-6600"],
            },
            {
                "query_id": "q2",
                "query": "CS 5800",
                "expected_course_ids": ["c-cs-5800"],
            },
            {
                "query_id": "q3",
                "query": "AAI 9999",
                "expected_course_ids": [],  # adversarial
            },
        ],
    }

    routes = {
        "AAI 6600": ["c-aai-6600"],
        "CS 5800": ["c-other", "c-cs-5800"],  # CS 5800 found at rank 2
        "AAI 9999": [],  # correctly rejected
    }
    report = run_eval(test_set, lambda q: routes[q], k=5)

    # 2 queries with expected; recall: 1.0 + 1.0 / 2 = 1.0; MRR: 1.0 + 0.5 / 2 = 0.75
    assert report.queries_with_expected == 2
    assert report.recall_at_5 == 1.0
    assert report.mrr == 0.75


def test_run_eval_records_per_query_results() -> None:
    test_set = {"queries": [
        {"query_id": "q1", "query": "x",
         "expected_course_ids": ["c-1"]},
    ]}
    report = run_eval(test_set, lambda q: ["c-1"])
    assert len(report.per_query) == 1
    assert isinstance(report.per_query[0], QueryResult)
    assert report.per_query[0].hit is True


def test_run_eval_no_queries_with_expected_yields_zero_recall() -> None:
    """Test set of only adversarial queries."""
    test_set = {"queries": [
        {"query_id": "q1", "query": "AAI 9999", "expected_course_ids": []},
    ]}
    report = run_eval(test_set, lambda q: [])
    assert report.queries_with_expected == 0
    # MRR / Recall stay at 0 default since denominator is 0
    assert report.recall_at_5 == 0.0
    assert report.mrr == 0.0


# === to_dict / render ===

def test_to_dict_serializable() -> None:
    report = EvalReport(
        per_query=[QueryResult(
            query_id="q1", query="x", expected=["e"], retrieved=["e"],
            recall_at_5=1.0, reciprocal_rank=1.0,
        )],
        recall_at_5=1.0, mrr=1.0, queries_with_expected=1,
    )
    d = report.to_dict()
    assert d["summary"]["total_queries"] == 1
    assert d["summary"]["recall_at_5"] == 1.0
    assert d["per_query"][0]["query_id"] == "q1"


def test_render_text_marks_hit_and_miss() -> None:
    report = EvalReport(per_query=[
        QueryResult(query_id="q1", query="x", expected=["e"], retrieved=["e"],
                    recall_at_5=1.0, reciprocal_rank=1.0),
        QueryResult(query_id="q2", query="y", expected=["e"], retrieved=["other"],
                    recall_at_5=0.0, reciprocal_rank=0.0),
    ])
    out = render_text(report)
    assert "✓" in out
    assert "✗" in out
    assert "q1" in out
    assert "q2" in out
