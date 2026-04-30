"""RateMyProfessors GraphQL client.

RMP doesn't publish an official API. The web app uses a GraphQL endpoint at
https://www.ratemyprofessors.com/graphql with a public-but-unofficial Basic
Auth token (well-known: "test:test" base64 -> "dGVzdDp0ZXN0"). PLAN §9.1
acknowledges the ToS gray zone: GraphQL endpoint is preferable to scraping
HTML. Commercial use requires legal review.

== STATUS: SCAFFOLD ==

Interface (RmpReview + search_professor) is stable. The GraphQL query
templates need verification against the live schema, which RMP changes
periodically. Tests use canned JSON responses; live impl requires a fresh
schema probe before merging.
"""

from __future__ import annotations

import httpx
from pydantic import BaseModel, ConfigDict, Field

from scrapers._base import create_client, fetch_with_retry, logger

RMP_GRAPHQL_URL = "https://www.ratemyprofessors.com/graphql"

# Basic Auth: well-known public token used by the RMP web app.
# Visible in any RMP page's network tab. Not a credential we own.
RMP_AUTH_HEADER = "Basic dGVzdDp0ZXN0"

# Northeastern University RMP school ID.
# To verify: search "Northeastern University" on rmp web app, the URL has /school/<id>.
NEU_SCHOOL_ID = "U2Nob29sLTY5Ng=="  # Base64 for "School-696"; verify before use.


class RmpRating(BaseModel):
    """One numeric rating field with name + score."""

    model_config = ConfigDict(extra="forbid")

    name: str  # "overall" / "difficulty" / "would_take_again"
    score: float = Field(ge=0.0, le=5.0)


class RmpReview(BaseModel):
    """One student review with comment + ratings.

    Maps to evidence_snippets in schemas.course.Course later.
    """

    model_config = ConfigDict(extra="forbid")

    review_id: str = Field(min_length=1, description="RMP-side identifier for citation")
    comment: str
    overall_rating: float | None = Field(default=None, ge=0.0, le=5.0)
    difficulty_rating: float | None = Field(default=None, ge=0.0, le=5.0)
    would_take_again: bool | None = None
    course_code_mentioned: str | None = None  # student-typed, e.g. "CS5800"
    created_date: str | None = None  # ISO date string from RMP


class RmpProfessorSummary(BaseModel):
    """Aggregate stats + pulled reviews for one professor."""

    model_config = ConfigDict(extra="forbid")

    professor_id: str
    name: str
    department: str | None = None
    avg_rating: float | None = Field(default=None, ge=0.0, le=5.0)
    avg_difficulty: float | None = Field(default=None, ge=0.0, le=5.0)
    num_ratings: int = Field(default=0, ge=0)
    reviews: list[RmpReview] = Field(default_factory=list)


def search_professor(
    name: str,
    *,
    school_id: str = NEU_SCHOOL_ID,
    client: httpx.Client | None = None,
) -> RmpProfessorSummary | None:
    """Search RMP for a professor at a school. Returns None if not found.

    TODO(Week 2-3 live impl):
      1. POST GraphQL query to RMP_GRAPHQL_URL with Authorization header.
         Query template (verify against current RMP schema):
            query NewSearchTeachersQuery($query: TeacherSearchQuery!) {
              newSearch {
                teachers(query: $query) { edges { node {
                  id firstName lastName department avgRating
                  avgDifficulty numRatings ratings(first: 50) { edges { node {
                    id comment ratingTags class date helpfulRating clarityRating
                  } } }
                } } }
              }
            }
      2. Variables: {"query": {"text": name, "schoolID": school_id}}
      3. Pick best match (often just edges[0]). If multiple matches with
         same name, log a warning and return the highest-rated one.
      4. Map node fields -> RmpProfessorSummary; map ratings -> RmpReview.

    Schema gotcha: RMP renames fields. avgRating -> avgRatingRounded ->
    rating -> something else. Probe the schema first via __schema query.
    """
    raise NotImplementedError(
        "scrapers.rmp.search_professor: GraphQL impl pending; "
        "verify RMP schema before live run. See module docstring TODO."
    )


def _parse_professor_node(node: dict) -> RmpProfessorSummary:
    """Pure transform from GraphQL response node to RmpProfessorSummary.

    Separated for testing with canned JSON. Caller handles HTTP + auth.
    """
    raise NotImplementedError("scrapers.rmp._parse_professor_node: pending")


__all__ = [
    "NEU_SCHOOL_ID",
    "RMP_GRAPHQL_URL",
    "RmpProfessorSummary",
    "RmpRating",
    "RmpReview",
    "search_professor",
]
