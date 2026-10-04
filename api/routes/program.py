"""GET /programs + GET /programs/{program_id} — program-ontology browsing.

GET /programs + GET /programs/{program_id} —— 培养方案本体浏览。

The Layer 3 ontology (programs / required-course edges) was previously
only reachable sideways: through /course/{id}'s program_context or the
chat route's program-aware shortcut. These two public read routes expose
it head-on so the UI can render a "browse by program" page — the listing
powers the program-card grid, the curriculum view powers the per-semester
course table.

Layer 3 本体（培养方案 / 必修课程边）此前只能侧面触及：要么经
/course/{id} 的 program_context，要么走 chat 路由里感知培养方案的捷径。
这两个公开只读路由把它正面暴露出来，让 UI 能渲染一个"按培养方案浏览"
页面 —— 列表接口驱动培养方案卡片网格，课程表接口驱动按学期分组的课程
表格。

No auth: these records are public, but legacy seeds are NOT verified catalog facts (same tier as
/course/{id}). The give-to-get gate only guards Co-op contributions.

无需鉴权：这些记录公开，但旧 seed 不是已核验目录事实（与 /course/{id} 同一层级）。
贡献换权限门只守护 Co-op 贡献内容。

Response models live HERE rather than api/models.py — they are private to
this route pair and nothing else consumes them; keeping them local avoids
churning the shared transport-model module for a leaf feature.

响应模型放在这里而不是 api/models.py —— 它们只服务于这一对路由，没有
其他地方消费；放在本地可以避免为一个末梢功能去搅动共享的传输模型模块。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field

from api.dependencies import DbConn, get_course_repo, get_program_policy_reader, get_program_repo
from db.program_plan_repository import ProgramPlanRepository
from db.program_repository import ProgramNotFound, ProgramRepository
from db.repository import CourseRepository
from schemas.program_plan import ProgramPlan
from schemas.program_policy_view import ProgramPolicyView
from rag.program_policy_evidence import ProgramPolicyReader

router = APIRouter(prefix="/programs", tags=["programs"])


# === Response models (route-private — api/models.py stays untouched) ===


class ProgramSummaryOut(BaseModel):
    """One row of the /programs listing: Program + its curriculum size.
    /programs 列表里的一行：一个 Program 及其课程表规模。"""

    model_config = ConfigDict(extra="forbid")

    program_id: str
    full_name: str
    prefix: str
    department: str | None = None
    college: str | None = None
    course_count: int
    plan_count: int = 0
    warnings: list[str] = Field(default_factory=lambda: ["legacy_seed_unverified", "legacy_scope_unknown"])


class CurriculumCourseOut(BaseModel):
    """One course inside a semester group, display fields resolved from
    the catalog. Edges whose course_id is missing from `courses` (dangling
    seed edge) are dropped by the route, so code/name are always present.
    某个学期分组内的一门课程，显示字段已从目录解析。course_id 在 `courses`
    中缺失的边（悬空的种子边）会被路由丢弃，因此 code/name 必定存在。"""

    model_config = ConfigDict(extra="forbid")

    course_id: str
    primary_code: str
    primary_name: str
    requirement_type: str
    notes: str | None = None


class CurriculumSemesterOut(BaseModel):
    """Semester group. semester=None means 'no recorded recommendation', NOT
    permission to enroll in any term, and it always sorts last.
    学期分组。semester=None 表示"没有记录推荐学期"，不是任意学期可修，
    并且始终排在最后。"""

    model_config = ConfigDict(extra="forbid")

    semester: int | None = None
    courses: list[CurriculumCourseOut]


class ProgramCurriculumOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    program_id: str
    full_name: str
    prefix: str
    notes: str | None = None
    semesters: list[CurriculumSemesterOut]
    plans: list[ProgramPlan] = Field(default_factory=list)
    plan_schema_available: bool = False
    warnings: list[str] = Field(default_factory=lambda: ["legacy_seed_unverified", "legacy_scope_unknown"])


class ProgramPlansOut(BaseModel):
    program_id: str
    schema_available: bool
    plans: list[ProgramPlan]
    warnings: list[str] = Field(default_factory=lambda: ["personal_catalog_applicability_unconfirmed", "not_an_eligibility_evaluator"])


# === Routes ===


@router.get(
    "",
    response_model=list[ProgramSummaryOut],
    summary="List seeded programs (with curriculum size)",
    description=(
        "Returns every seeded program with its required-course edge count. "
        "Public read, not gated content. Legacy seeds have unverified scope; "
        "plan_count counts usable version-scoped documents, not verified full degrees.\n\n"
        "`course_count` counts curriculum EDGES (including edges whose "
        "course hasn't been scraped yet), so it can exceed the number of "
        "rows the curriculum view renders."
    ),
    responses={
        200: {"description": "Program list (possibly empty before seeding)."},
    },
)
async def list_programs(
    conn: DbConn,
    program_repo: Annotated[ProgramRepository, Depends(get_program_repo)],
) -> list[ProgramSummaryOut]:
    out: list[ProgramSummaryOut] = []
    for program in program_repo.list_programs():
        # N+1 by design: the seeded program set is ≤4 rows, so one extra
        # SELECT per program is cheaper to maintain than a custom JOIN.
        # 中文：故意接受 N+1 —— 预置的培养方案集合 ≤4 行，每个培养方案多
        # 发一次 SELECT，比维护一个自定义 JOIN 更划算。
        edges = program_repo.list_required_courses(program.program_id)
        out.append(
            ProgramSummaryOut(
                program_id=program.program_id,
                full_name=program.full_name,
                prefix=program.prefix,
                department=program.department,
                college=program.college,
                course_count=len(edges),
                plan_count=len(ProgramPlanRepository(conn).list_for_program(program.program_id)),
            )
        )
    return out


@router.get(
    "/{program_id}",
    response_model=ProgramCurriculumOut,
    summary="Program curriculum grouped by recommended semester",
    description=(
        "Returns one program's required courses grouped by "
        "`semester_recommended`, display names resolved from the catalog "
        "in a single batched SELECT.\n\n"
        "Groups are ordered semester 1, 2, ... with the no-recommendation "
        "group (`semester: null` — no semester information, NOT anytime eligibility) last. Edges "
        "whose course_id is missing from the `courses` table (dangling "
        "seed edge, course not yet scraped) are silently dropped rather "
        "than failing the whole curriculum view."
    ),
    responses={
        200: {"description": "Curriculum found and returned."},
        404: {"description": "program_id not in `programs` table."},
    },
)
async def get_program_curriculum(
    program_id: str,
    conn: DbConn,
    program_repo: Annotated[ProgramRepository, Depends(get_program_repo)],
    course_repo: Annotated[CourseRepository, Depends(get_course_repo)],
) -> ProgramCurriculumOut:
    try:
        program = program_repo.get_program(program_id)
    except ProgramNotFound as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Program {program_id!r} not found",
        ) from e

    edges = program_repo.list_required_courses(program_id)
    # ONE batched SELECT for display names — per-edge get() would be N+1
    # on the largest curriculum (and get_batch already powers /course/{id}).
    # 中文：用一次批量 SELECT 取显示名称 —— 若逐边调用 get()，在最大的课程表
    # 上会退化成 N+1（而且 get_batch 本就是 /course/{id} 用的那套）。
    courses = course_repo.get_batch([e.course_id for e in edges])

    # Group by semester. The repo orders edges (non-null semesters
    # ascending, NULL last, course_id within), so one ordered pass over a
    # plain insertion-ordered dict produces groups in final display order.
    # 中文：按学期分组。repo 已经排好边的顺序（非空学期升序、NULL 排最后，
    # 组内再按 course_id），所以只需对一个普通的、保留插入顺序的 dict 做
    # 一趟遍历，分组结果自然就是最终展示顺序。
    groups: dict[int | None, list[CurriculumCourseOut]] = {}
    for edge in edges:
        resolved = courses.get(edge.course_id)
        if resolved is None:
            continue  # dangling seed edge — skip, don't 500 the view / 悬空种子边，跳过，不让视图 500
        groups.setdefault(edge.semester_recommended, []).append(
            CurriculumCourseOut(
                course_id=edge.course_id,
                primary_code=resolved.primary_code,
                primary_name=resolved.primary_name,
                requirement_type=edge.requirement_type,
                notes=edge.notes,
            )
        )

    return ProgramCurriculumOut(
        program_id=program.program_id,
        full_name=program.full_name,
        prefix=program.prefix,
        notes=program.notes,
        semesters=[
            CurriculumSemesterOut(semester=sem, courses=cs)
            for sem, cs in groups.items()
        ],
        plans=ProgramPlanRepository(conn).list_for_program(program_id),
        plan_schema_available=ProgramPlanRepository(conn).available(),
    )


@router.get("/{program_id}/plans", response_model=ProgramPlansOut,
            summary="Version-scoped requirement documents (not eligibility decisions)")
async def get_program_plans(
    program_id: str, conn: DbConn,
    program_repo: Annotated[ProgramRepository, Depends(get_program_repo)],
    campus: Annotated[str | None, Query(pattern=r"^[a-z][a-z0-9-]{0,39}$")] = None,
    catalog_year: Annotated[str | None, Query(pattern=r"^\d{4}-\d{4}$")] = None,
    pathway: Annotated[str | None, Query(pattern=r"^(standard|align|bridge)$")] = None,
) -> ProgramPlansOut:
    try:
        program_repo.get_program(program_id)
    except ProgramNotFound as exc:
        raise HTTPException(status_code=404, detail="program_id not found") from exc
    if catalog_year:
        start, end = map(int, catalog_year.split("-"))
        if end != start + 1:
            raise HTTPException(status_code=422, detail="Catalog year must be consecutive")
    repo = ProgramPlanRepository(conn)
    return ProgramPlansOut(program_id=program_id, schema_available=repo.available(),
                           plans=repo.list_for_program(program_id, campus=campus, catalog_year=catalog_year, pathway=pathway))


@router.get("/{program_id}/plans/{plan_id}/policies", response_model=ProgramPolicyView,
    summary="Read-only evidence for one exact current plan, not eligibility",
    description="Missing, stale or unusable policy sources return explicit states with no usable fragments. "
                "No latest-edition fallback, auto-fetch, DB writes or merged policy decisions.")
async def get_selected_program_policies(
    program_id: str, plan_id: str, conn: DbConn, response: Response,
    program_repo: Annotated[ProgramRepository, Depends(get_program_repo)],
    policy_reader: Annotated[ProgramPolicyReader, Depends(get_program_policy_reader)],
) -> ProgramPolicyView:
    try:
        program_repo.get_program(program_id)
    except ProgramNotFound as exc:
        raise HTTPException(status_code=404, detail="program_id not found") from exc
    plans = ProgramPlanRepository(conn).list_for_program(program_id)
    plan = next((item for item in plans if item.plan_id == plan_id), None)
    if plan is None:
        raise HTTPException(status_code=404, detail="No usable current plan with this ID in the selected program")
    response.headers["Cache-Control"] = "no-store"
    return policy_reader.read(plan)
