"""RateMyProfessors GraphQL client (live impl per PLAN_v2.0 §4.4 P0).

RMP doesn't publish an official API. The web app uses a GraphQL endpoint at
https://www.ratemyprofessors.com/graphql with a public-but-unofficial Basic
Auth token (well-known: "test:test" base64 -> "dGVzdDp0ZXN0"). PLAN §9.1
acknowledges the ToS gray zone — this code is for academic research only;
commercial deployment requires legal review.

Schema verified 2026-05-03 via scripts/probe_rmp.py. Field names that have
churned in past RMP releases:
  qualityRating / overallRating / classRating  → currently `qualityRating` (int 1-5)
  difficultyRating / difficultyRatingRounded   → currently `difficultyRatingRounded`
  wouldTakeAgain (per-rating bool)              → no longer surfaced; only
                                                   wouldTakeAgainPercent at teacher level
If those drift again, refresh tests/fixtures/rmp/teacher_search.json via
scripts/probe_rmp.py --save and update _parse_review_node accordingly.
"""

from __future__ import annotations

import re
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from scrapers._base import create_client, fetch_with_retry, logger

RMP_GRAPHQL_URL = "https://www.ratemyprofessors.com/graphql"

# Basic Auth: well-known public token used by the RMP web app. Not a credential we own.
RMP_AUTH_HEADER = "Basic dGVzdDp0ZXN0"

# Northeastern University main Boston campus, verified 2026-05-03 (legacyId=696).
NEU_SCHOOL_ID = "U2Nob29sLTY5Ng=="  # base64("School-696")

# Course code that students type into RMP: "PHTH2210" / "AAI 6600" / "ds5230a".
# We canonicalize to "DEPT NUMBER[LETTER]" (matches schemas.course COURSE_CODE_PATTERN).
_RMP_CODE_RE = re.compile(r"^\s*([A-Za-z]{2,4})\s?(\d{4}[A-Za-z]?)\s*$")

# RMP date format: "YYYY-MM-DD HH:MM:SS +0000 UTC". We only keep the calendar date.
_RMP_DATE_HEAD_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")

_TEACHER_QUERY = """
query SearchTeacher($query: TeacherSearchQuery!) {
  newSearch {
    teachers(query: $query, first: 5) {
      edges {
        node {
          id legacyId firstName lastName department
          school { name }
          avgRating avgDifficulty numRatings wouldTakeAgainPercent
          ratings(first: 25) {
            edges {
              node {
                id comment date class qualityRating
                difficultyRatingRounded ratingTags
              }
            }
          }
        }
      }
    }
  }
}
"""


class RmpReview(BaseModel):
    """One student review with comment + ratings."""

    model_config = ConfigDict(extra="forbid")

    review_id: str = Field(min_length=1)
    comment: str
    overall_rating: float | None = Field(default=None, ge=0.0, le=5.0)
    difficulty_rating: float | None = Field(default=None, ge=0.0, le=5.0)
    would_take_again: bool | None = None
    course_code_mentioned: str | None = None
    created_date: str | None = None
    rating_tags: list[str] = Field(default_factory=list)


class RmpProfessorSummary(BaseModel):
    """Aggregate stats + pulled reviews for one professor."""

    model_config = ConfigDict(extra="forbid")

    professor_id: str
    name: str
    department: str | None = None
    avg_rating: float | None = Field(default=None, ge=0.0, le=5.0)
    avg_difficulty: float | None = Field(default=None, ge=0.0, le=5.0)
    num_ratings: int = Field(default=0, ge=0)
    would_take_again_percent: float | None = Field(default=None, ge=0.0, le=100.0)
    reviews: list[RmpReview] = Field(default_factory=list)


# A mostly-empty Rating placeholder kept for backward compat with existing tests.
class RmpRating(BaseModel):
    """One numeric rating field with name + score (legacy shape)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    score: float = Field(ge=0.0, le=5.0)


class RmpQueryError(RuntimeError):
    """RMP GraphQL returned an `errors` block (schema drift, bad input, etc)."""


# === Public entry point ===


def search_professor(
    name: str,
    *,
    school_id: str = NEU_SCHOOL_ID,
    client: httpx.Client | None = None,
) -> RmpProfessorSummary | None:
    """Search RMP for one professor at a school. Returns None if no match.

    Picks edges[0] (RMP's relevance ranking, which already factors in
    review count and recency). Logs a warning if multiple matches at the
    same school — caller may want to disambiguate by passing a more
    specific name.
    """
    own_client = client is None
    if own_client:
        client = create_client(
            extra_headers={
                "Authorization": RMP_AUTH_HEADER,
                "Content-Type": "application/json",
            }
        )
    try:
        log = logger.bind(scraper="rmp", name=name, school_id=school_id)
        log.info("rmp.search.start")
        body = {
            "query": _TEACHER_QUERY,
            "variables": {"query": {"text": name, "schoolID": school_id}},
        }
        # The shared client may not have RMP auth — inject per request.
        headers = {
            "Authorization": RMP_AUTH_HEADER,
            "Content-Type": "application/json",
        }
        resp = fetch_with_retry(client, RMP_GRAPHQL_URL, method="POST",
                                json=body, headers=headers)
        data = resp.json()

        if "errors" in data and data["errors"]:
            log.error("rmp.graphql_errors", errors=data["errors"])
            raise RmpQueryError(f"RMP GraphQL errors: {data['errors']}")

        edges = (
            (data.get("data") or {})
            .get("newSearch", {})
            .get("teachers", {})
            .get("edges", [])
        ) or []
        if not edges:
            log.info("rmp.no_match")
            return None
        if len(edges) > 1:
            log.info("rmp.multiple_matches", count=len(edges))

        return _parse_professor_node(edges[0]["node"])
    finally:
        if own_client:
            client.close()


# === Pure parsers (no I/O) ===


def _parse_professor_node(node: dict[str, Any]) -> RmpProfessorSummary:
    """GraphQL teacher node → RmpProfessorSummary. Defensive against missing keys."""
    first = (node.get("firstName") or "").strip()
    last = (node.get("lastName") or "").strip()
    full_name = " ".join(p for p in (first, last) if p) or "Unknown"

    rating_edges = ((node.get("ratings") or {}).get("edges") or [])
    reviews = [_parse_review_node(e.get("node") or {}) for e in rating_edges]
    reviews = [r for r in reviews if r is not None]

    return RmpProfessorSummary(
        professor_id=node.get("id") or "",
        name=full_name,
        department=node.get("department"),
        avg_rating=_clamp_rating(node.get("avgRating")),
        avg_difficulty=_clamp_rating(node.get("avgDifficulty")),
        num_ratings=int(node.get("numRatings") or 0),
        would_take_again_percent=_clamp_percent(node.get("wouldTakeAgainPercent")),
        reviews=reviews,
    )


def _parse_review_node(node: dict[str, Any]) -> RmpReview | None:
    """One rating node → RmpReview. Returns None if review_id is missing
    (defensive against partial responses)."""
    review_id = node.get("id")
    if not review_id:
        return None
    return RmpReview(
        review_id=str(review_id),
        comment=node.get("comment") or "",
        overall_rating=_clamp_rating(node.get("qualityRating")),
        difficulty_rating=_clamp_rating(node.get("difficultyRatingRounded")),
        would_take_again=None,  # not surfaced per-review by current schema
        course_code_mentioned=_normalize_course_code(node.get("class")),
        created_date=_normalize_date(node.get("date")),
        rating_tags=_parse_rating_tags(node.get("ratingTags")),
    )


def _normalize_course_code(raw: str | None) -> str | None:
    """Loose RMP class string → canonical 'DEPT NUMBER'. None if unparseable."""
    if not raw:
        return None
    m = _RMP_CODE_RE.match(raw)
    if not m:
        return None
    return f"{m.group(1).upper()} {m.group(2).upper()}"


def _normalize_date(raw: str | None) -> str | None:
    """RMP datetime → 'YYYY-MM-DD'. None if no head match."""
    if not raw:
        return None
    m = _RMP_DATE_HEAD_RE.match(raw.strip())
    return m.group(1) if m else None


def _parse_rating_tags(raw: str | None) -> list[str]:
    """RMP encodes multiple tags as 'Tag A--Tag B--Tag C'. Single tag has no
    delimiter. Returns [] for None / '' so the caller doesn't have to guard."""
    if not raw:
        return []
    return [t.strip() for t in raw.split("--") if t.strip()]


def _clamp_rating(v: Any) -> float | None:
    """Coerce to float and require [0, 5]. Returns None for null / out-of-range."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if 0.0 <= f <= 5.0:
        return f
    return None


def _clamp_percent(v: Any) -> float | None:
    """Coerce to float and require [0, 100]. Returns None for null / out-of-range
    (RMP returns -1 for 'not enough data')."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if 0.0 <= f <= 100.0:
        return f
    return None


__all__ = [
    "NEU_SCHOOL_ID",
    "RMP_AUTH_HEADER",
    "RMP_GRAPHQL_URL",
    "RmpProfessorSummary",
    "RmpQueryError",
    "RmpRating",
    "RmpReview",
    "search_professor",
]
