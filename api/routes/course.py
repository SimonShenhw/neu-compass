"""GET /course/{course_id} — full Course detail.

Returns the rehydrated Pydantic Course (PLAN §2.2 v1.1 shape). The
response is whatever lives in courses.generated_json — including soft
fields with their evidence_snippets, since the UI's evidence-bubble
component (Week 6 deliverable) needs the source quotes.

Tier-aware Co-op data is intentionally NOT mixed in here. The UI calls
GET /coop?course_id=... separately, and that endpoint applies the
visibility filter. Keeping concerns separate avoids smearing two
authorization rules into one response shape.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import get_course_repo
from db.repository import CourseNotFound, CourseRepository
from schemas.course import Course

router = APIRouter(prefix="/course", tags=["course"])


@router.get(
    "/{course_id}",
    response_model=Course,
    summary="Get full Course detail",
    description=(
        "Returns the rehydrated Pydantic Course (schema v1.1, see "
        "`schemas/course.py`). Includes soft fields (workload, difficulty, "
        "skill_tags, career_relevance, controversial_signals) **with their "
        "evidence_snippets** when present — the UI's evidence-bubble "
        "component uses these for source-quote display.\n\n"
        "Co-op data is **not** mixed in; call `GET /coop?course_id=...` "
        "separately so visibility-tier authorization stays in one place."
    ),
    responses={
        200: {"description": "Course found and returned."},
        404: {"description": "course_id not in `courses` table."},
    },
)
async def get_course(
    course_id: str,
    course_repo: Annotated[CourseRepository, Depends(get_course_repo)],
) -> Course:
    try:
        return course_repo.get(course_id)
    except CourseNotFound as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Course {course_id!r} not found",
        ) from e
