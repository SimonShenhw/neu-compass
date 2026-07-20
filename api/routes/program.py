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

No auth: program curricula are public catalog facts (same tier as
/course/{id}). The give-to-get gate only guards Co-op contributions.

无需鉴权：培养方案课程表是公开目录事实（与 /course/{id} 同一层级）。
贡献换权限门只守护 Co-op 贡献内容。

Response models live HERE rather than api/models.py — they are private to
this route pair and nothing else consumes them; keeping them local avoids
churning the shared transport-model module for a leaf feature.

响应模型放在这里而不是 api/models.py —— 它们只服务于这一对路由，没有
其他地方消费；放在本地可以避免为一个末梢功能去搅动共享的传输模型模块。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict

from api.dependencies import get_course_repo, get_program_repo
from db.program_repository import ProgramNotFound, ProgramRepository
from db.repository import CourseRepository

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
    """Semester group. semester=None means 'no recommended slot' — the UI
    labels that group "anytime" (任意学期) and it always sorts last.
    学期分组。semester=None 表示"没有推荐学期"—— UI 把这组标为"任意学期"，
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


# === Routes ===


@router.get(
    "",
    response_model=list[ProgramSummaryOut],
    summary="List seeded programs (with curriculum size)",
    description=(
        "Returns every seeded program with its required-course edge count. "
        "Public read — program curricula are catalog facts, not gated "
        "content.\n\n"
        "`course_count` counts curriculum EDGES (including edges whose "
        "course hasn't been scraped yet), so it can exceed the number of "
        "rows the curriculum view renders."
    ),
    responses={
        200: {"description": "Program list (possibly empty before seeding)."},
    },
)
async def list_programs(
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
        "group (`semester: null` — render as \"anytime\") last. Edges "
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
    )
