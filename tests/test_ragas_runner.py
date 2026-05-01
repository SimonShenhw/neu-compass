"""Tests for eval.ragas_runner — input builder + result flattener.

The actual ragas.evaluate() call is NOT exercised here (would need a real
LLM key). The data-shaping logic is covered against fakes.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from unittest.mock import MagicMock

import pandas as pd
import pytest

from db.repository import CourseRepository
from eval.ragas_runner import (
    RagasInput,
    _flatten_ragas_result,
    build_ragas_inputs,
)
from rag.retriever import SearchHit
from schemas.course import Course


@dataclass
class _FakeRetriever:
    course_repo: CourseRepository
    course_ids_by_query: dict[str, list[str]]

    def search(self, query, *, k=10):
        cids = self.course_ids_by_query.get(query, [])[:k]
        return [
            SearchHit(course=self.course_repo.get(cid), score=1.0 / (i + 1))
            for i, cid in enumerate(cids)
        ]


@pytest.fixture
def setup(empty_db: sqlite3.Connection):
    course_repo = CourseRepository(empty_db)
    course_repo.insert(
        Course(course_id="c-algo", primary_code="CS 5800",
               primary_name="Algorithms",
               topics_covered=["graph algorithms"]),
        raw_text="Course on graph algorithms",
    )
    course_repo.insert(
        Course(course_id="c-ml", primary_code="DS 5220",
               primary_name="ML"),
        raw_text="Course on neural networks",
    )
    return course_repo


# === build_ragas_inputs ===

def test_build_inputs_one_query(setup) -> None:
    course_repo = setup
    retriever = _FakeRetriever(course_repo, {"q1": ["c-algo"]})
    test_set = {"queries": [
        {"query_id": "q1", "query": "q1", "expected_course_ids": ["c-algo"]},
    ]}
    inputs = build_ragas_inputs(test_set, retriever, course_repo, k=3)

    assert len(inputs) == 1
    assert inputs[0].question == "q1"
    assert "graph algorithms" in inputs[0].contexts[0]
    assert "CS 5800" in inputs[0].ground_truth


def test_build_inputs_multiple_queries(setup) -> None:
    course_repo = setup
    retriever = _FakeRetriever(course_repo, {
        "q1": ["c-algo"],
        "q2": ["c-ml", "c-algo"],
    })
    test_set = {"queries": [
        {"query_id": "q1", "query": "q1", "expected_course_ids": ["c-algo"]},
        {"query_id": "q2", "query": "q2",
         "expected_course_ids": ["c-ml"]},
    ]}
    inputs = build_ragas_inputs(test_set, retriever, course_repo, k=3)

    assert len(inputs) == 2
    assert len(inputs[1].contexts) == 2  # both retrieved


def test_build_inputs_adversarial_empty_ground_truth(setup) -> None:
    """Adversarial queries (no expected_course_ids) → empty ground_truth."""
    course_repo = setup
    retriever = _FakeRetriever(course_repo, {"q1": ["c-algo"]})
    test_set = {"queries": [
        {"query_id": "q1", "query": "q1", "expected_course_ids": []},
    ]}
    inputs = build_ragas_inputs(test_set, retriever, course_repo, k=3)
    assert inputs[0].ground_truth == ""


def test_build_inputs_respects_k(setup) -> None:
    course_repo = setup
    retriever = _FakeRetriever(course_repo, {
        "q1": ["c-algo", "c-ml"],
    })
    test_set = {"queries": [{"query_id": "q1", "query": "q1",
                              "expected_course_ids": ["c-algo"]}]}
    inputs = build_ragas_inputs(test_set, retriever, course_repo, k=1)
    assert len(inputs[0].contexts) == 1


def test_build_inputs_handles_unknown_expected_id(setup) -> None:
    """Reference to a non-existent course_id should be silently skipped, not crash."""
    course_repo = setup
    retriever = _FakeRetriever(course_repo, {"q1": ["c-algo"]})
    test_set = {"queries": [{
        "query_id": "q1", "query": "q1",
        "expected_course_ids": ["c-algo", "c-does-not-exist"],
    }]}
    inputs = build_ragas_inputs(test_set, retriever, course_repo, k=3)
    # Got the one valid course in ground_truth; non-existent one skipped
    assert "CS 5800" in inputs[0].ground_truth


def test_ragas_input_shape() -> None:
    inp = RagasInput(question="q", contexts=["c1"], ground_truth="gt")
    assert inp.question == "q"
    assert inp.contexts == ["c1"]


# === _flatten_ragas_result ===

def test_flatten_dict_result() -> None:
    fake = {"context_precision": 0.85, "context_recall": 0.72,
             "extra_string_field": "ignored"}
    flat = _flatten_ragas_result(fake)
    assert flat == {"context_precision": 0.85, "context_recall": 0.72}


def test_flatten_pandas_result() -> None:
    """Newer Ragas returns a Result with .to_pandas()."""
    fake = MagicMock()
    fake.to_pandas.return_value = pd.DataFrame({
        "context_precision": [0.9, 0.8, 1.0],
        "context_recall": [0.7, 0.75, 0.65],
        "question": ["q1", "q2", "q3"],  # non-numeric, should be filtered
    })
    flat = _flatten_ragas_result(fake)
    assert flat["context_precision"] == pytest.approx(0.9, abs=0.0001)
    assert flat["context_recall"] == pytest.approx(0.7, abs=0.0001)
    assert "question" not in flat


def test_flatten_unknown_shape_raises() -> None:
    with pytest.raises(TypeError, match="Unknown Ragas result shape"):
        _flatten_ragas_result("not a dict, not a result")
