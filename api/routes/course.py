"""GET /course/{course_id} — full Course detail + program-ontology context.

GET /course/{course_id} —— 完整课程详情 + 培养方案本体上下文。

Returns the rehydrated Pydantic Course (PLAN §2.2 v1.1 shape). The
response is whatever lives in courses.generated_json — including soft
fields with their evidence_snippets, since the UI's evidence-bubble
component (Week 6 deliverable) needs the source quotes — plus two
ontology lists resolved at request time (Layer 3, 2026-06 UI round 2):

  - program_context: which seeded programs require this course, as what
    (core / foundation / elective_pool / capstone) and in which semester.
  - prerequisites: this course's prereq edges with display names resolved
    in one batched SELECT.

返回还原后的 Pydantic Course（PLAN §2.2 v1.1 形状）。响应内容就是
courses.generated_json 里存的那些 —— 包括带 evidence_snippets 的软字段，
因为 UI 的证据气泡组件（Week 6 交付物）需要源引文 —— 外加两份在请求时
即时解析出的本体列表（Layer 3，2026-06 UI 第二轮）：

  - program_context：哪些预置培养方案要求本课程、以什么身份要求
    （core / foundation / elective_pool / capstone）、推荐第几学期。
  - prerequisites：本课程的先修边，用一次批量 SELECT 解析出显示名称。

Tier-aware Co-op data is intentionally NOT mixed in here. The UI calls
GET /coop?course_id=... separately, and that endpoint applies the
visibility filter. Keeping concerns separate avoids smearing two
authorization rules into one response shape.

分层可见的 Co-op 数据故意不混进这里。UI 会单独调用
GET /coop?course_id=...，由那个端点应用可见性过滤。关注点分离，避免把
两套授权规则揉进同一个响应形状里。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import get_course_repo, get_program_repo
from api.models import CourseDetailOut, CoursePrereqOut, CourseProgramEdgeOut
from db.program_repository import ProgramRepository
from db.repository import CourseNotFound, CourseRepository

router = APIRouter(prefix="/course", tags=["course"])


@router.get(
    "/{course_id}",
    response_model=CourseDetailOut,
    summary="Get full Course detail (+ program context)",
    description=(
        "Returns the rehydrated Pydantic Course (schema v1.1, see "
        "`schemas/course.py`). Includes soft fields (workload, difficulty, "
        "skill_tags, career_relevance, controversial_signals) **with their "
        "evidence_snippets** when present — the UI's evidence-bubble "
        "component uses these for source-quote display.\n\n"
        "Additionally resolves the Layer 3 ontology context: "
        "`program_context` (programs whose curriculum lists this course) "
        "and `prerequisites` (prereq edges with display names). Both are "
        "`[]` for courses outside any seeded program.\n\n"
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
    program_repo: Annotated[ProgramRepository, Depends(get_program_repo)],
) -> CourseDetailOut:
    try:
        course = course_repo.get(course_id)
    except CourseNotFound as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Course {course_id!r} not found",
        ) from e

    program_context = [
        CourseProgramEdgeOut(
            program_id=program.program_id,
            program_name=program.full_name,
            requirement_type=edge.requirement_type,
            semester_recommended=edge.semester_recommended,
        )
        for program, edge in program_repo.list_programs_for_course(course_id)
    ]

    prereq_edges = program_repo.list_prerequisites(course_id)
    prereq_courses = course_repo.get_batch(
        [p.prereq_course_id for p in prereq_edges],
    )
    prerequisites = []
    for p in prereq_edges:
        resolved = prereq_courses.get(p.prereq_course_id)
        prerequisites.append(
            CoursePrereqOut(
                course_id=p.prereq_course_id,
                primary_code=resolved.primary_code if resolved else None,
                primary_name=resolved.primary_name if resolved else None,
                requirement=p.requirement,
            )
        )

    return CourseDetailOut(
        **course.model_dump(),
        program_context=program_context,
        prerequisites=prerequisites,
    )
