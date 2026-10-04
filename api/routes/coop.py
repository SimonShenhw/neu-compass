"""Private Co-op collection; reviewed publication and field-level give-to-get.

中文：先私有收集，人工脱敏审核后按不同贡献者门控公开；字段按贡献数解锁。
"""

from __future__ import annotations

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import DbConn, get_coop_repo, get_coop_submission_repo, get_current_user_id, get_user_repo
from api.models import CoopOut, CoopUploadRequest, CoopUploadResponse
from db.coop_repository import CoopRepository
from db.coop_submission_repository import CoopSubmissionRepository
from db.user_repository import UserRepository
from schemas.coop import CoopExperience, derive_visibility

router = APIRouter(prefix="/coop", tags=["coop"])
log = structlog.get_logger("neu_compass.coop")


def _derive_visibility(req: CoopUploadRequest) -> int:
    """Content-driven field tier, never client-chosen / 内容决定分层。"""
    return derive_visibility(
        interview_summary=req.interview_summary, technical_questions=req.technical_questions,
        salary_range_usd=req.salary_range_usd,
    )


@router.post(
    "", response_model=CoopUploadResponse, status_code=status.HTTP_201_CREATED,
    summary="Collect a private Co-op submission for review",
    description=(
        "Authenticated uploads are accepted into a PRIVATE pending queue, not published. "
        "A curator must supply reviewed/redacted content; publication requires at least "
        "two distinct authenticated contributors with the same company/role/term. "
        "Seeds and repeat submissions cannot establish this threshold. "
        "Contribution credit is awarded only once per contributor/reviewed group at publication. "
        "Retries return the existing submission without replacing its content. "
        "'accepted' means stored, NOT publicly visible; 'status' reports the review state. "
        "visibility_level is content-derived; contributor identity comes from a signed Bearer session."
    ),
    responses={
        201: {"description": "Private submission stored, or existing submission returned."},
        401: {"description": "Missing, invalid, expired token, or unknown user."},
        422: {"description": "Invalid payload."},
        503: {"description": "Moderation schema has not been migrated."},
    },
)
def upload_coop(
    req: CoopUploadRequest, conn: DbConn,
    submissions: Annotated[CoopSubmissionRepository, Depends(get_coop_submission_repo)],
    user_repo: Annotated[UserRepository, Depends(get_user_repo)],
    x_user_id: Annotated[str | None, Depends(get_current_user_id)] = None,
) -> CoopUploadResponse:
    if not x_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: log in and send "
                   "Authorization: Bearer <session_token> (ADR-0021)",
        )
    # A signed token can outlive its user row (7-day max_age vs. account
    # deletion); without this check the contributor_user_id FK fails as a
    # 500. Same 401 contract as /auth/me — the client clears its session.
    # 中文：签名令牌的存活时间可能超过用户行本身（7 天 max_age vs. 账号被
    # 删除）；不做这个检查，contributor_user_id 外键会失败并抛 500。与
    # /auth/me 相同的 401 约定 —— 客户端清空会话。
    if user_repo.get(x_user_id) is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unknown user. Log in again.",
        )


    new_coop = CoopExperience(
        coop_id=f"coop-{uuid.uuid4().hex[:12]}", **req.model_dump(),
        contributor_user_id=x_user_id, is_seed_data=False,
        visibility_level=_derive_visibility(req),
    )
    row, duplicate = submissions.submit(new_coop)
    stored = CoopExperience.model_validate_json(row["payload"])
    credited = conn.execute(
        "SELECT 1 FROM coop_contribution_credits WHERE user_id=? AND group_key=? AND coop_id=?",
        (x_user_id, row["group_key"], row["coop_id"]),
    ).fetchone() is not None
    user = user_repo.get(x_user_id)
    conn.commit()
    # Do not log company, role, term, or free text from the private queue.
    # 中文：私有待审字段不写入应用日志。
    log.info("coop.collected", coop_id=row["coop_id"], review_status=row["review_status"], duplicate=duplicate)
    return CoopUploadResponse(
        coop_id=row["coop_id"], accepted=True, visibility_level=stored.visibility_level,
        status=row["review_status"], duplicate=duplicate,
        contribution_credited=credited, contribution_count=user.contribution_count,
    )


@router.get(
    "",
    response_model=list[CoopOut],
    summary="List Co-op records (give-to-get, field-level redaction)",
    description=(
        "Returns curated seeds and reviewed UGC with at least two distinct "
        "contributors; applies tier-gated FIELD redaction server-side "
        "(PLAN §6.4):\n\n"
        "- tier 0 (anonymous / no contributions): company, role, term, "
        "industry, duration visible; interview/technical/salary `null`.\n"
        "- tier 1 (contribution_count ≥ 1): + `interview_summary`, "
        "`technical_questions`.\n"
        "- tier 2 (contribution_count ≥ 2): + `salary_range_usd`.\n\n"
        "`visibility_level` reports the row's intrinsic tier (from content "
        "presence), so clients can render 'contribute to unlock' hints for "
        "redacted fields.\n\n"
        "Each row is sanitized: `contributor_user_id` and `redaction_audit` "
        "are server-internal and NOT returned."
    ),
    responses={
        200: {"description": "Eligible public Co-op records (redacted per tier)."},
        503: {"description": "Moderation schema has not been migrated."},
    },
)
def list_coop(
    coop_repo: Annotated[CoopRepository, Depends(get_coop_repo)],
    submissions: Annotated[CoopSubmissionRepository, Depends(get_coop_submission_repo)],
    user_repo: Annotated[UserRepository, Depends(get_user_repo)],
    x_user_id: Annotated[str | None, Depends(get_current_user_id)] = None,
) -> list[CoopOut]:
    tier = 0
    if x_user_id:
        user = user_repo.get(x_user_id)
        if user is not None:
            tier = min(user.contribution_count, 2)

    return [
        CoopOut(
            coop_id=c.coop_id,
            company=c.company,
            role=c.role,
            industry=c.industry.value if c.industry else None,
            coop_term=c.coop_term,
            duration_months=c.duration_months,
            related_courses=c.related_courses,
            # Field-level give-to-get gate — redaction happens HERE,
            # server-side; clients never receive what their tier hasn't
            # earned.
            # 中文：字段级贡献换权限门 —— 脱敏就发生在这里、服务端完成；
            # 客户端永远收不到其分层还未挣到的内容。
            interview_summary=c.interview_summary if tier >= 1 else None,
            technical_questions=c.technical_questions if tier >= 1 else None,
            salary_range_usd=c.salary_range_usd if tier >= 2 else None,
            visibility_level=c.visibility_level,
        )
        for c in coop_repo.list_public()
    ]
