"""API transport models — request/response shapes.

API 传输模型 —— 请求/响应形状。

Kept distinct from schemas/* (which is the domain layer). The Course
schema is reused as-is for /course/{id}, but anything user-typed (search
queries, Co-op uploads) goes through the API model first so we control the
public contract.

与 schemas/*（领域层）保持区分。Course 这个 schema 原样复用给
/course/{id}，但任何用户输入的内容（搜索查询、Co-op 上传）都要先经过
API 模型这一层，这样我们才能掌控对外契约。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from schemas.coop import Industry
from schemas.course import Course
from schemas.answer_evidence import CourseAnswerEvidence
from schemas.course_requisite_document import CourseRequisiteListing


# === /search ===


class SearchRequest(BaseModel):
    """Search query body. Filters are optional; all combine with AND.
    搜索请求体。过滤条件均为可选，多个条件之间以 AND 组合。"""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    k: int = Field(default=10, ge=1, le=50)
    term: str | None = None
    credits: int | None = Field(default=None, ge=0, le=12)
    delivery_mode: str | None = None  # validated against DeliveryMode in route / 在路由层校验
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
    """How a course fits into one seeded program (Layer 3 ontology).
    一门课程如何嵌入某个预置培养方案（Layer 3 本体）。"""

    model_config = ConfigDict(extra="forbid")

    program_id: str
    program_name: str
    requirement_type: str
    semester_recommended: int | None = None


class CoursePrereqOut(BaseModel):
    """A prerequisite edge with the prereq's display fields resolved.
    code/name are None when the prereq course isn't in the catalog
    (dangling seed edge) — the UI then shows the raw course_id.
    一条先修边，先修课程的显示字段已解析。当先修课程不在目录中时
    （悬空的种子边），code/name 为 None —— 此时 UI 会直接显示原始
    course_id。"""

    model_config = ConfigDict(extra="forbid")

    course_id: str
    primary_code: str | None = None
    primary_name: str | None = None
    requirement: str


class CourseDetailOut(Course):
    """Course (schema v1.1, unchanged fields) + program-ontology context.

    Course（schema v1.1，字段未变）+ 培养方案本体上下文。

    Subclass instead of wrapper so existing /course/{id} consumers keep
    their flat field access; the two new lists default to empty for
    courses outside any seeded program.

    用子类而不是包装类，这样 /course/{id} 现有的消费方仍能保持扁平的
    字段访问方式；对不属于任何预置培养方案的课程，这两个新列表默认
    为空。"""

    program_context: list[CourseProgramEdgeOut] = Field(default_factory=list)
    prerequisites: list[CoursePrereqOut] = Field(default_factory=list)
    answer_evidence: CourseAnswerEvidence = Field(default_factory=CourseAnswerEvidence)
    course_requisites: CourseRequisiteListing = Field(default_factory=CourseRequisiteListing)


# === /resolve/course ===


class ResolvedCourseOut(BaseModel):
    """One course a deep-link ref resolved to. Code + name ride along with
    the id so an ambiguous ref can be disambiguated in the UI without N
    follow-up /course calls.
    深链 ref 解析出的一门课程。code + name 与 id 一起返回，这样 UI 在遇到
    有歧义的 ref 时无需再发 N 次 /course 请求就能做消歧。"""

    model_config = ConfigDict(extra="forbid")

    course_id: str
    primary_code: str
    primary_name: str


class ResolveCourseResponse(BaseModel):
    """`matches` is empty when nothing resolved — a dead deep link is a
    normal outcome, not a 404. Clients treat ApiError as "API is down",
    so surfacing "no such course" as an exception would misreport it.
    没解析出任何结果时 `matches` 为空 —— 失效的深链是正常结果，不是 404。
    客户端把 ApiError 一律理解为「API 挂了」，若把「查无此课」抛成异常
    就会误报。"""

    model_config = ConfigDict(extra="forbid")

    ref: str
    matches: list[ResolvedCourseOut]


# === /chat ===


class ChatTurn(BaseModel):
    """One prior conversation turn (client-supplied — /chat is stateless;
    the Streamlit session owns the transcript and sends a recent window).
    一轮此前的对话（由客户端提供 —— /chat 本身是无状态的；由 Streamlit
    会话保管完整记录，只发送最近的一段窗口）。"""

    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    """Body for POST /chat. Filters mirror /search for re-use.

    POST /chat 的请求体。过滤字段与 /search 保持一致，便于复用。

    Conversation continuity (2026-06): `history` reaches the answer prompt
    (reference resolution + tone); `context_course_ids` are the previous
    turn's evidence — when the new query is a follow-up ("这门课作业量大吗"),
    retrieval short-circuits to those courses instead of searching a query
    that carries no course signal of its own.

    对话连续性（2026-06）：`history` 会传到回答用的 prompt 里（用于指代
    消解 + 语气延续）；`context_course_ids` 是上一轮的证据 —— 当新查询是
    追问（如"这门课作业量大吗"）时，检索直接短路到这些课程，而不是去
    搜索一个本身不带任何课程信号的查询。"""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    k: int = Field(default=5, ge=1, le=20)
    term: str | None = None
    credits: int | None = Field(default=None, ge=0, le=12)
    delivery_mode: str | None = None
    professor: str | None = None
    history: list[ChatTurn] = Field(default_factory=list, max_length=12)
    context_course_ids: list[str] = Field(default_factory=list, max_length=10)
    program_id: str | None = Field(default=None, min_length=1, max_length=64)

    # Only a JSON boolean; omitted/false preserves legacy no-answer-storage.
    # 中文：技术保存许可，不是身份／法律同意凭证；不得将字符串转成 true。
    allow_feedback_capture: bool = Field(default=False, strict=True)


# === /coop ===


class CoopUploadRequest(BaseModel):
    """Body for POST /coop. visibility_level is set server-side from content
    presence (interview / technical / salary), so clients don't pick their
    own tier.
    POST /coop 的请求体。visibility_level 由服务端根据内容是否存在
    （interview / technical / salary）来设定，客户端无法自选分层。"""

    model_config = ConfigDict(extra="forbid")

    company: str = Field(min_length=1)
    role: str = Field(min_length=1)
    coop_term: str | None = None
    industry: Industry | None = None
    duration_months: int | None = Field(default=None, ge=1, le=8)
    related_courses: list[str] = Field(default_factory=list)
    interview_summary: str | None = Field(default=None, max_length=10_000)
    technical_questions: str | None = Field(default=None, max_length=10_000)
    salary_range_usd: str | None = Field(default=None, max_length=10_000)

    @field_validator("company", "role", mode="before")
    @classmethod
    def strip_required_fields(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("coop_term", "interview_summary", "technical_questions", "salary_range_usd", mode="before")
    @classmethod
    def strip_optional_fields(cls, value):
        return (value.strip() or None) if isinstance(value, str) else value


class CoopUploadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    coop_id: str
    accepted: bool
    visibility_level: int
    status: Literal["pending", "approved", "rejected", "published"]
    duplicate: bool
    contribution_credited: bool
    contribution_count: int


class CoopOut(BaseModel):
    """Co-op view returned by GET /coop. Mirrors CoopExperience minus
    contributor_user_id / redaction_audit (internal audit fields, not for
    end users).
    GET /coop 返回的 Co-op 视图。与 CoopExperience 一致，但去掉了
    contributor_user_id / redaction_audit（内部审计字段，不面向终端
    用户）。"""

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
    query param Google redirected back with.
    POST /auth/callback 的请求体。Streamlit 页面发送 Google 重定向带回的
    `code` 查询参数。"""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    redirect_uri: str | None = None


class OAuthCallbackResponse(BaseModel):
    """Sanitized identity persisted server-side. Streamlit calls
    state_manager.login with these fields.

    经清洗、已持久化到服务端的身份信息。Streamlit 会用这些字段调用
    state_manager.login。

    session_token (ADR-0021): signed bearer credential for subsequent API
    calls (`Authorization: Bearer <token>`). None when the server runs
    without SESSION_SECRET (dev degraded mode).

    session_token（ADR-0021）：供后续 API 调用使用的签名 bearer 凭证
    （`Authorization: Bearer <token>`）。服务端未配置 SESSION_SECRET 时
    （开发降级模式）为 None。"""

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
    "refresh my profile" call.
    Bearer 会话令牌背后的身份（GET /auth/me）。让 UI 能从持久化的 cookie
    恢复登录状态而无需重新走一遍 OAuth —— 同时会从数据库重读
    contribution_count，因此它也是一个低成本的"刷新我的资料"调用。"""

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
    "ChatTurn",
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
    "ResolveCourseResponse",
    "ResolvedCourseOut",
    "SearchHitOut",
    "SearchRequest",
    "SearchResponse",
]
