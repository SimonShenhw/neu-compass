"""GET /resolve/course — deep-link reference (`?course=`) → course_ids.

GET /resolve/course —— 深链引用（`?course=`）→ course_id。

The UI receives a SHARED reference ('CS-5800', 'cs5800', 'Algo', or a raw
'neu-cs-5800') and needs an internal course_id before it can open the
detail panel. This route is that dictionary lookup: `resolve_course_ref`
(internal-id tier → alias tier via v_course_lookup), then one batched
SELECT for the display fields.

UI 拿到的是一个被分享出来的引用（'CS-5800'、'cs5800'、'Algo'，或者原始的
'neu-cs-5800'），要先换成内部 course_id 才能打开详情面板。本路由就是这次
字典查找：`resolve_course_ref`（内部 id 层 → 经 v_course_lookup 的别名
层），再用一次批量 SELECT 取显示字段。

Why not just call POST /search (whose stage 1 IS the alias tier):
  1. **query_log pollution.** Every /search call logs a row. Deep-link
     resolutions are machine traffic, not questions — mixing them in would
     corrupt the organic-query signal that the whole distribution push
     exists to collect (ADR-0028 ranked roadmap).
  2. **Cost.** An alias MISS in /search falls through to embed + BM25 +
     cross-encoder rerank (+ possibly a HyDE Gemini rescue): ~850ms p50 on
     the NAS to answer "is this link valid?".
  3. **Coverage.** A raw internal course_id isn't in v_course_lookup at
     all, so the alias tier alone can't resolve one.

为什么不直接调 POST /search（它的第 1 阶段就是别名层）：
  1. **污染 query_log。** 每次 /search 都会写一行日志。深链解析属于机器
     流量而非提问 —— 混进去会毁掉整个分发计划要采集的真实查询信号
     （见 ADR-0028 的排序路线图）。
  2. **代价。** /search 里别名未命中就会落到嵌入 + BM25 + 交叉编码器重排
     （还可能触发 HyDE 的 Gemini 救援）：在 NAS 上要用约 850ms 的 p50 去
     回答「这条链接有效吗」。
  3. **覆盖面。** 原始内部 course_id 根本不在 v_course_lookup 里，光靠
     别名层解析不出来。

Status filtering is deliberately NOT applied, matching GET /course/{id}
and /search's own alias path: this is an id lookup, not a search, and
ADR-0013's "pending courses must not leak" invariant is enforced on the
retrieval legs.

这里刻意不做 status 过滤，与 GET /course/{id} 以及 /search 自己的别名路径
保持一致：这是一次 id 查找而非搜索，ADR-0013 的「待审课程不得泄漏」不变式
由检索两路负责强制。
"""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Query

from api.dependencies import get_alias_repo, get_course_repo
from api.models import ResolveCourseResponse, ResolvedCourseOut
from db.alias_repository import AliasRepository
from db.repository import CourseRepository
from rag.query_normalizer import resolve_course_ref

router = APIRouter(prefix="/resolve", tags=["resolve"])

log = structlog.get_logger("neu_compass.resolve")

# Hard ceiling on the query param, well above resolve_course_ref's own
# MAX_COURSE_REF_LEN (64). Between the two, the resolver answers "no match"
# — that's a user with a mangled link. Above it, 422 — that's abuse.
# 中文：查询参数的硬上限，远高于 resolve_course_ref 自己的
# MAX_COURSE_REF_LEN（64）。介于两者之间由解析器回答「无匹配」——
# 那是链接被截断的用户。超过它则返回 422 —— 那是滥用。
MAX_REF_PARAM_LEN = 200


@router.get(
    "/course",
    response_model=ResolveCourseResponse,
    summary="Resolve a deep-link course reference to course_ids",
    description=(
        "Turns a shareable course reference into internal `course_id`s so "
        "the UI can open a `?course=` deep link.\n\n"
        "Accepted forms: internal id (`neu-cs-5800`), canonical code with "
        "any URL separator (`CS-5800`, `CS_5800`, `CS+5800`, `CS 5800`), "
        "the space-free spelling (`cs5800`), and any **approved** alias "
        "(`Algo`) — the same `v_course_lookup` view `/search`'s alias stage "
        "uses, so `review_status='pending'` aliases are excluded.\n\n"
        "Always 200. An unresolvable ref returns `matches: []` — a dead "
        "link is a normal outcome, not an error. `matches` may hold more "
        "than one course when the ref is ambiguous.\n\n"
        "**Not** logged to `query_log`: deep-link resolution is machine "
        "traffic and must not contaminate organic-query telemetry."
    ),
    responses={
        200: {
            "description": (
                "Resolution ran. `matches` is ordered most-specific first "
                "and is `[]` when nothing matched."
            ),
        },
        422: {"description": "`ref` missing, empty, or absurdly long."},
    },
)
def resolve_course(
    alias_repo: Annotated[AliasRepository, Depends(get_alias_repo)],
    course_repo: Annotated[CourseRepository, Depends(get_course_repo)],
    ref: Annotated[
        str,
        Query(
            min_length=1,
            max_length=MAX_REF_PARAM_LEN,
            description="The raw `?course=` value, e.g. `CS-5800`.",
        ),
    ],
) -> ResolveCourseResponse:
    course_ids = resolve_course_ref(
        ref, alias_repo=alias_repo, course_repo=course_repo,
    )

    # One batched SELECT for the display fields. Ids it can't hydrate are
    # dropped, so the response never hands the UI a course_id that
    # GET /course/{id} would then 404 on. Belt-and-braces rather than a
    # live failure mode: v_course_lookup INNER JOINs courses, so a
    # dangling alias row is already invisible to the alias tier — this
    # only catches a delete racing between the two statements.
    # 中文：一次批量 SELECT 取显示字段。取不到的 id 直接丢弃，这样响应
    # 绝不会把一个 GET /course/{id} 随后会 404 的 course_id 交给 UI。
    # 这属于双保险而非现实故障路径：v_course_lookup 对 courses 做的是
    # INNER JOIN，悬空的别名行对别名层本就不可见 —— 这里只兜住两条语句
    # 之间恰好发生删除的竞态。
    resolved = course_repo.get_batch(course_ids)
    matches = [
        ResolvedCourseOut(
            course_id=course.course_id,
            primary_code=course.primary_code,
            primary_name=course.primary_name,
        )
        for cid in course_ids
        if (course := resolved.get(cid)) is not None
    ]

    log.info(
        "resolve.course",
        ref=ref[:80],
        count=len(matches),
        dangling=len(course_ids) - len(matches),
    )
    return ResolveCourseResponse(ref=ref, matches=matches)
