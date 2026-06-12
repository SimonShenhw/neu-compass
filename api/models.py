"""API transport models — request/response shapes.

Kept distinct from schemas/* (which is the domain layer). The Course
schema is reused as-is for /course/{id}, but anything user-typed (search
queries, Co-op uploads) goes through the API model first so we control the
public contract.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from schemas.coop import Industry
from schemas.course import Course


# === /search ===


class SearchRequest(BaseModel):
    """Search query body. Filters are optional; all combine with AND."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    k: int = Field(default=10, ge=1, le=50)
    term: str | None = None
    credits: int | None = Field(default=None, ge=0, le=12)
    delivery_mode: str | None = None  # validated against DeliveryMode in route
    professor: str | None = None


class SearchHitOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_id: str
    primary_code: str
    primary_name: str
    score: float
    matched_via: Literal["alias", "hybrid"]


class SearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    k: int
    matched_via: Literal["alias", "hybrid", "empty", "rejected"]
    results: list[SearchHitOut]
    latency_ms: float
    rejection_reason: str | None = None


# === /course/{id} ===


class CourseProgramEdgeOut(BaseModel):
    """How a course fits into one seeded program (Layer 3 ontology)."""

    model_config = ConfigDict(extra="forbid")

    program_id: str
    program_name: str
    requirement_type: str
    semester_recommended: int | None = None


class CoursePrereqOut(BaseModel):
    """A prerequisite edge with the prereq's display fields resolved.
    code/name are None when the prereq course isn't in the catalog
    (dangling seed edge) — the UI then shows the raw course_id."""

    model_config = ConfigDict(extra="forbid")

    course_id: str
    primary_code: str | None = None
    primary_name: str | None = None
    requirement: str


class CourseDetailOut(Course):
    """Course (schema v1.1, unchanged fields) + program-ontology context.

    Subclass instead of wrapper so existing /course/{id} consumers keep
    their flat field access; the two new lists default to empty for
    courses outside any seeded program."""

    program_context: list[CourseProgramEdgeOut] = Field(default_factory=list)
    prerequisites: list[CoursePrereqOut] = Field(default_factory=list)


# === /chat ===


class ChatRequest(BaseModel):
    """Body for POST /chat. Filters mirror /search for re-use."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    k: int = Field(default=5, ge=1, le=20)
    term: str | None = None
    credits: int | None = Field(default=None, ge=0, le=12)
    delivery_mode: str | None = None
    professor: str | None = None


# === /coop ===


class CoopUploadRequest(BaseModel):
    """Body for POST /coop. visibility_level is set server-side from content
    presence (interview / technical / salary), so clients don't pick their
    own tier."""

    model_config = ConfigDict(extra="forbid")

    company: str = Field(min_length=1)
    role: str = Field(min_length=1)
    coop_term: str | None = None
    industry: Industry | None = None
    duration_months: int | None = Field(default=None, ge=1, le=8)
    related_courses: list[str] = Field(default_factory=list)
    interview_summary: str | None = Field(default=None, max_length=10_000)
    technical_questions: str | None = Field(default=None, max_length=10_000)
    salary_range_usd: str | None = None


class CoopUploadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    coop_id: str
    accepted: bool
    visibility_level: int


class CoopOut(BaseModel):
    """Co-op view returned by GET /coop. Mirrors CoopExperience minus
    contributor_user_id / redaction_audit (internal audit fields, not for
    end users)."""

    model_config = ConfigDict(extra="forbid")

    coop_id: str
    company: str
    role: str
    industry: str | None
    coop_term: str | None
    duration_months: int | None
    related_courses: list[str]
    interview_summary: str | None
    technical_questions: str | None
    salary_range_usd: str | None
    visibility_level: int


# === /auth/callback ===


class OAuthCallbackRequest(BaseModel):
    """Body for POST /auth/callback. The Streamlit page sends the `code`
    query param Google redirected back with."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    redirect_uri: str | None = None


class OAuthCallbackResponse(BaseModel):
    """Sanitized identity persisted server-side. Streamlit calls
    state_manager.login with these fields.

    session_token (ADR-0021): signed bearer credential for subsequent API
    calls (`Authorization: Bearer <token>`). None when the server runs
    without SESSION_SECRET (dev degraded mode)."""

    model_config = ConfigDict(extra="forbid")

    user_id: str
    email: str
    display_name: str | None = None
    contribution_count: int = 0
    session_token: str | None = None


class AuthMeResponse(BaseModel):
    """Identity behind a Bearer session token (GET /auth/me). Lets the UI
    restore login state from a persisted cookie without re-running OAuth —
    and re-reads contribution_count from the DB, so it's also the cheap
    "refresh my profile" call."""

    model_config = ConfigDict(extra="forbid")

    user_id: str
    email: str
    display_name: str | None = None
    contribution_count: int = 0


# === /health, /ready ===


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"


class ReadyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ready", "warming"]
    courses_indexed: int
    bm25_corpus: int


__all__ = [
    "AuthMeResponse",
    "ChatRequest",
    "CoopOut",
    "CoopUploadRequest",
    "CoopUploadResponse",
    "CourseDetailOut",
    "CoursePrereqOut",
    "CourseProgramEdgeOut",
    "HealthResponse",
    "OAuthCallbackRequest",
    "OAuthCallbackResponse",
    "ReadyResponse",
    "SearchHitOut",
    "SearchRequest",
    "SearchResponse",
]
