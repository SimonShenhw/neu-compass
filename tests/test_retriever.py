"""Tests for rag.retriever — uses real FAISS + a fake embedder."""

from __future__ import annotations

import sqlite3

import numpy as np
import pytest

from db.repository import CourseRepository
from rag.embedder import EMBEDDING_DIM, _l2_normalize
from rag.index import FaissIndex
from rag.retriever import ELIGIBLE_STATUS, Retriever
from schemas.course import Course, DeliveryMode


class _FixtureEmbedder:
    """Fake embedder backed by a dict text->vector. Tests preset what each
    text should embed to so we control similarity ranking exactly."""

    def __init__(self, mapping: dict[str, np.ndarray]):
        self._mapping = mapping

    def encode(self, texts: list[str], *, normalize: bool = True) -> np.ndarray:
        vecs = []
        for t in texts:
            if t not in self._mapping:
                raise KeyError(f"FixtureEmbedder has no vector for {t!r}")
            v = self._mapping[t]
            if v.ndim == 1:
                v = v.reshape(1, -1)
            vecs.append(v)
        out = np.vstack(vecs).astype(np.float32)
        return _l2_normalize(out) if normalize else out


def _vec(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.standard_normal(EMBEDDING_DIM, dtype=np.float32)


@pytest.fixture
def setup(empty_db: sqlite3.Connection):
    """Insert 3 courses, mark them indexed, build FAISS, return the bundle."""
    course_repo = CourseRepository(empty_db)

    courses = [
        Course(
            course_id="c-aai-6600", primary_code="AAI 6600",
            primary_name="Applied AI",
            credits=3, term="Spring 2026", delivery_mode=DeliveryMode.HYBRID,
        ),
        Course(
            course_id="c-cs-5800", primary_code="CS 5800",
            primary_name="Algorithms",
            credits=4, term="Spring 2026", delivery_mode=DeliveryMode.IN_PERSON,
        ),
        Course(
            course_id="c-ds-5220", primary_code="DS 5220",
            primary_name="ML Methods",
            credits=4, term="Fall 2025", delivery_mode=DeliveryMode.IN_PERSON,
        ),
    ]
    for c in courses:
        course_repo.insert(c)
        course_repo.mark_indexed(c.course_id)

    # Build FAISS with deterministic vectors keyed by raw_text proxy
    text_to_vec = {
        "ai course": _vec(1),
        "algorithms course": _vec(2),
        "ml course": _vec(3),
    }
    course_to_text = {
        "c-aai-6600": "ai course",
        "c-cs-5800": "algorithms course",
        "c-ds-5220": "ml course",
    }
    index = FaissIndex()
    vecs = np.vstack([text_to_vec[course_to_text[c.course_id]] for c in courses])
    index.add(_l2_normalize(vecs), [c.course_id for c in courses])

    embedder = _FixtureEmbedder(text_to_vec)
    retriever = Retriever(
        embedder=embedder,
        index=index,
        course_repo=course_repo,
        sqlite_conn=empty_db,
    )

    return retriever, course_repo, embedder, index, empty_db


# === Basic semantic search ===

def test_search_returns_top_k_hits(setup) -> None:
    retriever, *_ = setup
    hits = retriever.search("ai course", k=2)
    assert len(hits) == 2
    assert hits[0].course.course_id == "c-aai-6600"
    assert hits[0].score == pytest.approx(1.0, abs=1e-4)


def test_search_default_k(setup) -> None:
    retriever, *_ = setup
    hits = retriever.search("algorithms course")
    assert hits[0].course.course_id == "c-cs-5800"


# === Hard filter ===

def test_filter_by_term(setup) -> None:
    retriever, *_ = setup
    hits = retriever.search("ml course", hard_filters={"term": "Spring 2026"})
    course_ids = {h.course.course_id for h in hits}
    # DS 5220 is Fall 2025, should be filtered out
    assert "c-ds-5220" not in course_ids
    assert course_ids <= {"c-aai-6600", "c-cs-5800"}


def test_filter_by_credits(setup) -> None:
    retriever, *_ = setup
    hits = retriever.search("ai course", hard_filters={"credits": 4})
    course_ids = {h.course.course_id for h in hits}
    assert "c-aai-6600" not in course_ids
    assert course_ids <= {"c-cs-5800", "c-ds-5220"}


def test_filter_by_delivery_mode(setup) -> None:
    retriever, *_ = setup
    hits = retriever.search("ai course", hard_filters={"delivery_mode": "hybrid"})
    course_ids = {h.course.course_id for h in hits}
    assert course_ids == {"c-aai-6600"}


def test_filter_combination(setup) -> None:
    retriever, *_ = setup
    hits = retriever.search(
        "ai course",
        hard_filters={"term": "Spring 2026", "credits": 4},
    )
    course_ids = {h.course.course_id for h in hits}
    # Only CS 5800 fits both
    assert course_ids == {"c-cs-5800"}


def test_filter_no_matches_returns_empty(setup) -> None:
    retriever, *_ = setup
    hits = retriever.search(
        "ai course",
        hard_filters={"term": "Summer 2030"},  # no course
    )
    assert hits == []


# === ADR-0013: status filter ===

def test_pending_courses_excluded_from_results(
    setup, empty_db: sqlite3.Connection,
) -> None:
    """ADR-0013: Retriever must NOT return courses with status='pending'."""
    retriever, course_repo, _, index, _ = setup

    # Add a fourth course but leave status='pending' (no mark_indexed)
    pending_course = Course(
        course_id="c-pending",
        primary_code="MATH 7243",
        primary_name="Stats",
    )
    course_repo.insert(pending_course)
    # ALSO add to FAISS so it would appear in vector results if not filtered
    index.add(_l2_normalize(_vec(4).reshape(1, -1)), ["c-pending"])

    hits = retriever.search(
        "ai course",
        hard_filters={"credits": None},  # use a filter to exercise SQL path
    )
    course_ids = {h.course.course_id for h in hits}
    assert "c-pending" not in course_ids


def test_failed_courses_excluded(
    setup, empty_db: sqlite3.Connection,
) -> None:
    retriever, course_repo, _, index, _ = setup

    failed = Course(course_id="c-failed", primary_code="MATH 7243",
                    primary_name="Stats")
    course_repo.insert(failed)
    course_repo.mark_failed("c-failed")
    index.add(_l2_normalize(_vec(5).reshape(1, -1)), ["c-failed"])

    hits = retriever.search(
        "ai course",
        hard_filters={"credits": None},
    )
    assert "c-failed" not in {h.course.course_id for h in hits}


# === Without filters: searches whole index ===

def test_no_filter_searches_whole_index(setup) -> None:
    retriever, *_ = setup
    hits = retriever.search("ai course", k=10)
    course_ids = {h.course.course_id for h in hits}
    assert len(course_ids) == 3  # all indexed courses returned


def test_eligible_status_constant() -> None:
    """ADR-0013 invariant captured in the constant."""
    assert ELIGIBLE_STATUS == "indexed"


# === Score ordering ===

def test_results_ordered_by_score_desc(setup) -> None:
    retriever, *_ = setup
    hits = retriever.search("ai course", k=3)
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)
