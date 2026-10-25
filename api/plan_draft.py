"""The draft check behind POST /programs/{program_id}/plans/{plan_id}/draft (R4b): compute only, store nothing.

The React program page keeps the draft (course IDs) in memory and sends it with each change; this module turns that
list plus any newly typed codes into the draft the server stands behind, the notices the Streamlit page shows for the
same input, and `evaluate_draft`'s result for one exact source-checked plan. The per-code rules mirror
`app.plan_draft_view._add` step for step (unique match, exact primary code, a cross-listed twin counted once, an alias
under another primary code, identity and field checks, the 20-course limit), but run on the
repositories directly, so a lookup can never half-fail the way an HTTP call can. Nothing here writes a database row,
query_log or a log line with a course code or ID: the route logs counts only.

中文：草案核对（R4b）：只计算、不存储。React 的培养方案页把草案（课程 ID）放在内存里，每次变化都带过来；这里把它和这次
新输入的课号变成服务器认可的草案、Streamlit 对同样输入会显示的提示，以及按一份确切的已核对方案算出的 `evaluate_draft`
结果。每个课号的规则和 `app.plan_draft_view._add` 一步一步对应，但直接查仓库，不会像 HTTP 请求那样核对到一半失败。
这里不写数据库、不写 query_log，日志里也没有课号和课程 ID：路由只记个数。
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator

from db.alias_repository import AliasRepository
from db.repository import CourseRepository
from rag.query_normalizer import resolve_course_ref
from schemas.course import Course
from schemas.plan_draft import MAX_DRAFT_COURSES, DraftCourse, DraftResult, evaluate_draft, parse_course_codes
from schemas.program_plan import ProgramPlan

MAX_DRAFT_INPUT = 4000  # The Streamlit text area's max_chars. 中文：Streamlit 输入框的字数上限。
MAX_CANDIDATES = 10

CourseId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")]
NoticeKind = Literal["course_gone", "duplicate_code", "too_many_codes", "invalid_format", "invalid_format_more",
                     "all_present", "over_limit", "not_found", "ambiguous", "cross_listed_twin", "also_matches",
                     "primary_code", "invalid_record", "nothing_new"]


class DraftCheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    plan_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    course_ids: list[CourseId] = Field(default_factory=list, max_length=MAX_DRAFT_COURSES)
    input: str | None = Field(default=None, max_length=MAX_DRAFT_INPUT)

    @field_validator("course_ids")
    @classmethod
    def distinct(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("course_ids must be distinct")
        return value


class DraftCandidateOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    name: str


class DraftNoticeOut(BaseModel):
    """One line the page shows as plain text, in processing order. `text` is the Streamlit page's sentence for the
    same case; `candidates` only for `ambiguous` (at most 10, the rest counted in `candidates_omitted`).
    中文：页面按处理顺序当纯文字显示的一行。`text` 是 Streamlit 页面同一情况的那句话；`candidates` 只有 `ambiguous` 有。"""
    model_config = ConfigDict(extra="forbid")
    kind: NoticeKind
    level: Literal["warning", "info"]
    text: str
    candidates: list[DraftCandidateOut] = Field(default_factory=list, max_length=MAX_CANDIDATES)
    candidates_omitted: int = Field(default=0, ge=0)


class DraftCheckOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_content_sha256: str
    courses: list[DraftCourse] = Field(max_length=MAX_DRAFT_COURSES)
    added: list[str] = Field(max_length=MAX_DRAFT_COURSES)
    notices: list[DraftNoticeOut]
    result: DraftResult


def _notice(kind: NoticeKind, text: str, level: Literal["warning", "info"] = "warning", **extra) -> DraftNoticeOut:
    return DraftNoticeOut(kind=kind, level=level, text=text, **extra)


def _draft_course(course: Course) -> DraftCourse:
    return DraftCourse(course_id=course.course_id, code=course.primary_code, name=course.primary_name,
                       credits=course.credits)


def _current(course_ids: list[str], course_repo: CourseRepository) -> tuple[list[DraftCourse], list[DraftNoticeOut]]:
    """The draft as the server sees it now: a course whose record is gone or no longer valid leaves with a notice;
    two IDs now under one code keep the first. 中文：服务器现在看到的草案：记录没了或不再有效的课带一条提示离开；
    两个 ID 现在是同一个课号时留第一个。"""
    records = course_repo.get_batch(course_ids)
    courses: list[DraftCourse] = []
    notices: list[DraftNoticeOut] = []
    for course_id in course_ids:
        record = records.get(course_id)
        if record is None:
            notices.append(_notice("course_gone", "草案里有 1 门课在课程记录里找不到了，已从草案移除。"))
            continue
        try:
            course = _draft_course(record)
        except (ValidationError, ValueError):
            notices.append(_notice("invalid_record", record.primary_code + " 返回的课程身份或字段无效，未加入。"))
            continue
        if any(other.code == course.code for other in courses):
            notices.append(_notice("duplicate_code", "草案里有两门课现在是同一个课号 " + course.code + "，只保留一门。"))
            continue
        courses.append(course)
    return courses, notices


def _add(raw: str, existing: list[DraftCourse], *, course_repo: CourseRepository,
         alias_repo: AliasRepository) -> tuple[list[DraftCourse], list[DraftNoticeOut]]:
    """`app.plan_draft_view._add` on the repositories: the same order, limits and sentences.
    中文：在仓库上做 `app.plan_draft_view._add`：同样的顺序、上限和句子。"""
    notices: list[DraftNoticeOut] = []
    codes, invalid = parse_course_codes(raw)
    if len(codes) > MAX_DRAFT_COURSES:
        return [], [_notice("too_many_codes", "一次最多填写 20 门；本次没有加入课程。")]
    notices += [_notice("invalid_format", "课号格式不正确，未加入：" + token) for token in invalid[:10]]
    if len(invalid) > 10:
        notices.append(_notice("invalid_format_more", f"另有 {len(invalid)-10} 项格式不正确；未加入。"))
    known = {c.code for c in existing}
    pending = [code for code in codes if code not in known]
    if not pending:
        if codes:
            notices.append(_notice("all_present", "这些课号已在草案里，不会重复加入。", "info"))
        return [], notices
    excess = len(known) + len(pending) - MAX_DRAFT_COURSES
    if excess > 0:
        notices.append(_notice("over_limit", f"草案最多 20 门，本次尚未核对；请从输入减少 {excess} 门，"
                                             f"或从草案移除至少 {excess} 门。"))
        return [], notices
    accepted: list[DraftCourse] = []
    taken, twins = set(known), {}  # twins: a code an accepted course's other matches named -> that course.
    for code in pending:
        try:
            course_ids = resolve_course_ref(code, alias_repo=alias_repo, course_repo=course_repo)
            records = course_repo.get_batch(course_ids)
            hits = [(record, DraftCourse(course_id=record.course_id, code=record.primary_code, name=record.primary_name))
                    for course_id in course_ids if (record := records.get(course_id)) is not None]
            matches = [match for _, match in hits]
            if not matches:
                notices.append(_notice("not_found", "没有找到 " + code + "；未加入。"))
                continue
            if len(matches) != 1:
                exact = [m for m in matches if m.code == code]
                if len(exact) != 1:
                    notices.append(_notice("ambiguous", "对上多门，未加入；请核对完整课号：" + code,
                        candidates=[DraftCandidateOut(code=m.code, name=m.name) for m in matches[:MAX_CANDIDATES]],
                        candidates_omitted=max(0, len(matches) - MAX_CANDIDATES)))
                    continue
                match = exact[0]
                others = list(dict.fromkeys(m.code for m in matches if m != match))
            else:
                match, others = matches[0], []
            twin = twins.get(match.code) or next((other for other in others if other in taken), None)
            if twin:  # One course under two cross-listed codes counts once. 中文：交叉列出的两个课号只算一次。
                notices.append(_notice("cross_listed_twin", code + " 和 " + twin + " 可能是同一门交叉列出的课，只按 "
                                       + twin + " 计入；如果是两门不同的课，请向项目核实。"))
                continue
            if others:
                notices.append(_notice("also_matches", "按输入主课号核对 " + code + "；同一引用也匹配 "
                                       + "、".join(others[:10]) + "（可能交叉列出）；方案按哪个课号算，请向项目核实。"))
            record = next(record for record, hit in hits if hit is match)
            candidate = _draft_course(record)
            if candidate.course_id != match.course_id or candidate.code != match.code:
                raise ValueError("Course identity mismatch")
            accepted.append(candidate)
            taken.add(candidate.code)
            twins.update({other: candidate.code for other in others if other not in twins})
            if candidate.code != code:  # A single alias match under another primary code. 中文：别名换了主课号。
                notices.append(_notice("primary_code", "输入的 " + code + " 对应主课号 " + candidate.code + "，按 "
                                       + candidate.code + " 核对；方案按哪个课号算，请向项目核实。"))
        except (KeyError, TypeError, ValueError):  # ValidationError is a ValueError. 中文：ValidationError 也是 ValueError。
            notices.append(_notice("invalid_record", code + " 返回的课程身份或字段无效，未加入。"))
    if not accepted:
        return [], notices
    # Streamlit checks the limit again here because its session state can change under it; this list cannot: each
    # pending code adds at most one course and the check above bounds them, so the merge never passes 20.
    # 中文：Streamlit 在这里再查一次上限，因为它的会话状态可能被别处改；这里不会：每个待核对的课号最多加一门，
    # 上面已经限住了，合并后不会超过 20。
    merged = {c.code: c for c in existing}
    for course in accepted:
        merged.setdefault(course.code, course)
    if len(merged) == len(existing):
        notices.append(_notice("nothing_new", "没有新增课程；重复课号不会重复加入。", "info"))
        return [], notices
    return [course for code, course in merged.items() if code not in known], notices


def check_draft(plan: ProgramPlan, plan_content_sha256: str, body: DraftCheckIn, *, course_repo: CourseRepository,
                alias_repo: AliasRepository) -> DraftCheckOut:
    """`plan` is the exact source-checked plan the caller resolved for `plan_content_sha256`.
    中文：`plan` 是调用方按 `plan_content_sha256` 确认过的那份已核对方案。"""
    courses, notices = _current(body.course_ids, course_repo)
    added: list[DraftCourse] = []
    if body.input:
        added, more = _add(body.input, courses, course_repo=course_repo, alias_repo=alias_repo)
        notices += more
    courses = [*courses, *added]
    return DraftCheckOut(plan_content_sha256=plan_content_sha256, courses=courses, added=[c.code for c in added],
                         notices=notices, result=evaluate_draft(plan, courses))
