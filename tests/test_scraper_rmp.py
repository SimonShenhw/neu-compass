"""Tests for scrapers.rmp using fixture-backed real GraphQL responses.

Fixtures saved 2026-05-03 via scripts/probe_rmp.py --save:
  tests/fixtures/rmp/school_search.json   — Northeastern listing
  tests/fixtures/rmp/teacher_search.json  — sample teacher (Louisa Smith)
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from scrapers.rmp import (
    NEU_SCHOOL_ID,
    RMP_AUTH_HEADER,
    RMP_GRAPHQL_URL,
    RmpProfessorSummary,
    RmpQueryError,
    RmpReview,
    _clamp_percent,
    _clamp_rating,
    _normalize_course_code,
    _normalize_date,
    _parse_professor_node,
    _parse_rating_tags,
    _parse_review_node,
    search_professor,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "rmp"


def _fixture_json(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


# === Pydantic shape (kept here after stub graduation) ===


def test_review_minimal() -> None:
    r = RmpReview(review_id="rmp_1", comment="Tough but fair")
    assert r.overall_rating is None
    assert r.rating_tags == []


def test_review_rating_bounds() -> None:
    RmpReview(review_id="r1", comment="x", overall_rating=4.5, difficulty_rating=3.0)
    with pytest.raises(ValueError):
        RmpReview(review_id="r1", comment="x", overall_rating=5.5)
    with pytest.raises(ValueError):
        RmpReview(review_id="r1", comment="x", overall_rating=-1)


def test_review_extra_forbidden() -> None:
    with pytest.raises(ValueError):
        RmpReview(review_id="r1", comment="x", unexpected="x")  # type: ignore[call-arg]


def test_summary_minimal() -> None:
    s = RmpProfessorSummary(professor_id="p1", name="Dr. Smith")
    assert s.reviews == []
    assert s.num_ratings == 0
    assert s.would_take_again_percent is None


def test_summary_percent_bounds() -> None:
    RmpProfessorSummary(
        professor_id="p1", name="x", would_take_again_percent=75.0,
    )
    with pytest.raises(ValueError):
        RmpProfessorSummary(
            professor_id="p1", name="x", would_take_again_percent=120.0,
        )


def test_constants_present() -> None:
    assert RMP_GRAPHQL_URL.startswith("https://")
    assert RMP_AUTH_HEADER.startswith("Basic ")
    assert NEU_SCHOOL_ID  # non-empty


# === Pure helpers ===


def test_normalize_course_code_handles_variants() -> None:
    assert _normalize_course_code("PHTH2210") == "PHTH 2210"
    assert _normalize_course_code("AAI 6600") == "AAI 6600"
    assert _normalize_course_code("ds5230a") == "DS 5230A"
    assert _normalize_course_code("  cs 5800  ") == "CS 5800"


def test_normalize_course_code_rejects_garbage() -> None:
    assert _normalize_course_code(None) is None
    assert _normalize_course_code("") is None
    assert _normalize_course_code("N/A") is None
    assert _normalize_course_code("123") is None  # no dept letters
    assert _normalize_course_code("MATH99") is None  # only 2 digits


def test_normalize_date_extracts_calendar_date() -> None:
    assert _normalize_date("2025-04-24 16:44:51 +0000 UTC") == "2025-04-24"
    assert _normalize_date("2026-01-01") == "2026-01-01"
    assert _normalize_date(None) is None
    assert _normalize_date("") is None
    assert _normalize_date("not-a-date") is None


def test_parse_rating_tags_splits_on_double_dash() -> None:
    assert _parse_rating_tags("Clear grading criteria--Caring") == \
        ["Clear grading criteria", "Caring"]
    assert _parse_rating_tags("Lecture heavy") == ["Lecture heavy"]
    assert _parse_rating_tags("") == []
    assert _parse_rating_tags(None) == []


def test_clamp_rating_bounds() -> None:
    assert _clamp_rating(4.0) == 4.0
    assert _clamp_rating(0) == 0.0
    assert _clamp_rating(5) == 5.0
    assert _clamp_rating(None) is None
    assert _clamp_rating(-1) is None
    assert _clamp_rating(6) is None
    assert _clamp_rating("not a number") is None


def test_clamp_percent_bounds() -> None:
    assert _clamp_percent(75.0) == 75.0
    assert _clamp_percent(0) == 0.0
    assert _clamp_percent(100) == 100.0
    # RMP returns -1 for "not enough data" → None
    assert _clamp_percent(-1) is None
    assert _clamp_percent(150) is None
    assert _clamp_percent(None) is None


# === Pure parser against fixture ===


def test_parse_professor_node_against_fixture() -> None:
    """Sanity-check shape of parser output against captured RMP response."""
    data = _fixture_json("teacher_search.json")
    edges = data["data"]["newSearch"]["teachers"]["edges"]
    assert edges, "fixture should have teacher matches"

    summary = _parse_professor_node(edges[0]["node"])
    assert summary.professor_id
    assert summary.name == "Louisa Smith"
    assert summary.department == "Health Science"
    assert summary.avg_rating is not None
    assert 0 <= summary.avg_rating <= 5
    assert summary.num_ratings >= 1
    assert summary.reviews

    # First review should have comment, course code, and ratings
    r0 = summary.reviews[0]
    assert r0.review_id
    assert r0.comment
    assert r0.course_code_mentioned == "PHTH 2210"
    assert r0.overall_rating is not None
    assert r0.difficulty_rating is not None
    assert r0.created_date and r0.created_date.startswith("20")


def test_parse_review_node_returns_none_without_id() -> None:
    """Defensive against partial GraphQL responses (id missing)."""
    assert _parse_review_node({"comment": "x"}) is None


def test_parse_professor_node_handles_empty_ratings() -> None:
    summary = _parse_professor_node({
        "id": "T1", "firstName": "Jane", "lastName": "Doe",
        "department": "CS", "avgRating": None, "avgDifficulty": None,
        "numRatings": 0, "ratings": {"edges": []},
    })
    assert summary.reviews == []
    assert summary.avg_rating is None


# === HTTP layer (mocked transport) ===


def _client_serving(payload: dict, *, captured: dict | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured["url"] = str(request.url)
            captured["headers"] = dict(request.headers)
            captured["body"] = json.loads(request.content) if request.content else None
        return httpx.Response(200, json=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_search_professor_returns_summary() -> None:
    payload = _fixture_json("teacher_search.json")
    with _client_serving(payload) as client:
        summary = search_professor("smith", client=client)
    assert summary is not None
    assert summary.name == "Louisa Smith"
    assert len(summary.reviews) >= 1


def test_search_professor_attaches_auth_header() -> None:
    payload = _fixture_json("teacher_search.json")
    captured: dict = {}
    with _client_serving(payload, captured=captured) as client:
        search_professor("smith", client=client)
    # Auth header is required by RMP — without it we get 401.
    assert captured["headers"].get("authorization") == RMP_AUTH_HEADER


def test_search_professor_sends_school_id_in_variables() -> None:
    payload = _fixture_json("teacher_search.json")
    captured: dict = {}
    with _client_serving(payload, captured=captured) as client:
        search_professor("smith", school_id="custom-school", client=client)
    assert captured["body"]["variables"]["query"]["schoolID"] == "custom-school"
    assert captured["body"]["variables"]["query"]["text"] == "smith"


def test_search_professor_returns_none_on_no_match() -> None:
    empty_payload = {"data": {"newSearch": {"teachers": {"edges": []}}}}
    with _client_serving(empty_payload) as client:
        result = search_professor("nobody", client=client)
    assert result is None


def test_search_professor_raises_on_graphql_errors() -> None:
    err_payload = {
        "data": None,
        "errors": [{"message": "Field 'foo' not found"}],
    }
    with _client_serving(err_payload) as client:
        with pytest.raises(RmpQueryError, match="GraphQL"):
            search_professor("smith", client=client)
