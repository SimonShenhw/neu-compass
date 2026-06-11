"""Tests for the ADR-0019 HyDE rescue pass — rag.hyde.rescue_expand,
api.routes.common.attempt_hyde_rescue, and the /search wiring."""

from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from api.routes.common import attempt_hyde_rescue
from rag.hyde import RESCUE_PROMPT_TEMPLATE, rescue_expand
from rag.retriever import SearchHit
from schemas.course import Course
from tests.conftest import build_test_app


# === rescue_expand ===


def test_rescue_expand_reject_verdict_returns_none() -> None:
    assert rescue_expand("asdf qwerty", generate_fn=lambda p: "REJECT") is None


def test_rescue_expand_reject_with_whitespace_and_case() -> None:
    assert rescue_expand("x", generate_fn=lambda p: "  reject\n") is None


def test_rescue_expand_empty_output_returns_none() -> None:
    assert rescue_expand("x", generate_fn=lambda p: "   ") is None


def test_rescue_expand_passes_description_through() -> None:
    desc = "This course covers PAC learning and VC dimension theory."
    out = rescue_expand("VC dimension PAC learning", generate_fn=lambda p: desc)
    assert out == desc


def test_rescue_prompt_includes_query() -> None:
    captured: list[str] = []

    def fake(prompt: str) -> str:
        captured.append(prompt)
        return "REJECT"

    rescue_expand("CRM 认知偏差", generate_fn=fake)
    assert "CRM 认知偏差" in captured[0]
    assert "REJECT" in RESCUE_PROMPT_TEMPLATE


# === attempt_hyde_rescue (fakes) ===


class _FakeHybrid:
    """Returns canned hits; records the query it was given."""

    def __init__(self, hits: list[SearchHit]) -> None:
        self._hits = hits
        self.last_query: str | None = None

    def search(self, query, *, hard_filters=None, k=10):
        self.last_query = query
        return self._hits[:k]


class _FakeReranker:
    def score(self, query, candidates):
        return [0.9 for _ in candidates]


def _hit(cid: str = "c-1") -> SearchHit:
    return SearchHit(
        course=Course(course_id=cid, primary_code="CS 5800",
                      primary_name="Algorithms"),
        score=0.5,
    )


def _conn_with_courses() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE courses (course_id TEXT PRIMARY KEY, raw_text TEXT)")
    conn.execute("INSERT INTO courses VALUES ('c-1', 'graph algorithms text')")
    return conn


def test_rescue_code_pattern_query_never_consults_llm() -> None:
    """'AAI 9999' reaching the gate means the alias tier missed → the
    course doesn't exist. The rescue must decline WITHOUT asking the LLM
    (live probe: Gemini judges fake codes plausible and rescues them)."""
    calls: list[str] = []

    def spy(q: str) -> str | None:
        calls.append(q)
        return "a description"

    out = attempt_hyde_rescue(
        query="AAI 9999", conn=_conn_with_courses(),
        hybrid=_FakeHybrid([_hit()]), reranker=_FakeReranker(),
        rescue_fn=spy,
        hard_filters=None, pool_size=10, blend_alpha=0.4, top_k=5,
    )
    assert out is None
    assert calls == []  # LLM never consulted


def test_rescue_declined_returns_none() -> None:
    out = attempt_hyde_rescue(
        query="asdf", conn=_conn_with_courses(),
        hybrid=_FakeHybrid([_hit()]), reranker=_FakeReranker(),
        rescue_fn=lambda q: None,
        hard_filters=None, pool_size=10, blend_alpha=0.4, top_k=5,
    )
    assert out is None


def test_rescue_llm_exception_degrades_to_none() -> None:
    def boom(q: str) -> str | None:
        raise RuntimeError("gemini down")

    out = attempt_hyde_rescue(
        query="x", conn=_conn_with_courses(),
        hybrid=_FakeHybrid([_hit()]), reranker=_FakeReranker(),
        rescue_fn=boom,
        hard_filters=None, pool_size=10, blend_alpha=0.4, top_k=5,
    )
    assert out is None


def test_rescue_empty_retrieval_returns_none() -> None:
    out = attempt_hyde_rescue(
        query="x", conn=_conn_with_courses(),
        hybrid=_FakeHybrid([]), reranker=_FakeReranker(),
        rescue_fn=lambda q: "a hypothetical description",
        hard_filters=None, pool_size=10, blend_alpha=0.4, top_k=5,
    )
    assert out is None


def test_rescue_success_reretrieves_with_expansion() -> None:
    hybrid = _FakeHybrid([_hit()])
    out = attempt_hyde_rescue(
        query="VC dimension PAC learning", conn=_conn_with_courses(),
        hybrid=hybrid, reranker=_FakeReranker(),
        rescue_fn=lambda q: "Covers computational learning theory.",
        hard_filters=None, pool_size=10, blend_alpha=0.4, top_k=5,
    )
    assert out is not None and len(out) == 1
    # Combined query = original + expansion (HyDE prepend-original pattern).
    assert hybrid.last_query is not None
    assert hybrid.last_query.startswith("VC dimension PAC learning")
    assert "learning theory" in hybrid.last_query


# === /search route wiring ===


def test_search_rejected_query_rescued_end_to_end(
    empty_db: sqlite3.Connection,
) -> None:
    """Word-overlap FixtureReranker rejects 'zzz nonexistent topic' (max
    sigmoid 0 < 0.05). With a rescue fn whose expansion lexically matches
    the algorithms course, the route must return hybrid results instead."""
    from api.dependencies import get_hyde_rescue_fn  # noqa: PLC0415

    app = build_test_app(empty_db, seed=True)
    app.dependency_overrides[get_hyde_rescue_fn] = lambda: (
        lambda q: "This course covers graph algorithms BFS DFS shortest paths."
    )
    with TestClient(app) as client:
        r = client.post("/search", json={"query": "zzz nonexistent topic", "k": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["matched_via"] == "hybrid"
    assert any(h["primary_code"] == "CS 5800" for h in body["results"])


def test_search_rejected_query_stays_rejected_when_rescue_declines(
    empty_db: sqlite3.Connection,
) -> None:
    from api.dependencies import get_hyde_rescue_fn  # noqa: PLC0415

    app = build_test_app(empty_db, seed=True)
    app.dependency_overrides[get_hyde_rescue_fn] = lambda: (lambda q: None)
    with TestClient(app) as client:
        r = client.post("/search", json={"query": "zzz nonexistent topic", "k": 3})
    assert r.status_code == 200
    assert r.json()["matched_via"] == "rejected"


def test_search_rescue_disabled_by_default(empty_db: sqlite3.Connection) -> None:
    """settings.hyde_rescue defaults False → dependency yields None → the
    rejection path is byte-identical to pre-ADR-0019 behavior."""
    app = build_test_app(empty_db, seed=True)
    with TestClient(app) as client:
        r = client.post("/search", json={"query": "zzz nonexistent topic", "k": 3})
    assert r.status_code == 200
    assert r.json()["matched_via"] == "rejected"
