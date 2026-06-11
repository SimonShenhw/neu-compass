"""POST /coop — k-anonymity-gated upload. GET /coop — visibility-tier list.

PII red lines (PLAN §3.4 / §6.3 / ADR §3.4):
  - The (company, role, coop_term) triple must satisfy k=2 anonymity AFTER
    insert: the new row plus existing rows with the same triple total ≥ 2.
    Enforced server-side via schemas.coop.is_uniquely_identifying — clients
    cannot bypass.
  - visibility_level is set server-side from content presence, NOT from the
    client. salary_range_usd → 2 (premium). interview/technical → 1
    (detail). bare row → 0 (preview). This stops a client from publishing
    salary at level=0 just by lying.
  - User identity comes from a SIGNED session token (ADR-0021,
    `Authorization: Bearer`) minted only by POST /auth/callback after the
    Google OAuth round-trip — the old trusted X-User-Id header let anyone
    on the network read salary-tier data or impersonate contributors.

GET /coop returns rows visible to the user per CoopRepository
.list_visible_to_user (PLAN §6.4 give-to-get gate). Anonymous request
sees only level-0 rows (default contribution_count=0).
"""

from __future__ import annotations

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import (
    DbConn,
    get_coop_repo,
    get_current_user_id,
    get_user_repo,
)
from api.models import (
    CoopOut,
    CoopUploadRequest,
    CoopUploadResponse,
)
from db.coop_repository import CoopRepository
from db.user_repository import UserRepository
from schemas.coop import CoopExperience, is_uniquely_identifying

router = APIRouter(prefix="/coop", tags=["coop"])

log = structlog.get_logger("neu_compass.coop")


def _derive_visibility(req: CoopUploadRequest) -> int:
    """visibility_level is content-driven, not client-chosen.

    Tier rules (PLAN §6.4):
      2 — salary_range_usd present (premium)
      1 — interview_summary or technical_questions present (detail)
      0 — only public-tier fields (preview)
    """
    if req.salary_range_usd:
        return 2
    if req.interview_summary or req.technical_questions:
        return 1
    return 0


@router.post(
    "",
    response_model=CoopUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit Co-op experience (k=2 anonymity gated)",
    description=(
        "Upload a Co-op record. **Server-side enforcements** (clients cannot "
        "bypass):\n\n"
        "- **k=2 anonymity**: the (company, role, coop_term) triple must "
        "appear ≥2 times across the corpus *after* insert. Violations "
        "return 422 with a generalization hint.\n"
        "- **visibility_level** is derived from content presence, NOT "
        "client-chosen:\n"
        "  - `2` (premium) when `salary_range_usd` present\n"
        "  - `1` (detail) when `interview_summary` or `technical_questions` "
        "present\n"
        "  - `0` (preview) otherwise\n\n"
        "User identity comes from `Authorization: Bearer <session_token>` "
        "(ADR-0021) — tokens are minted only by `POST /auth/callback`.\n\n"
        "**F1 compliance** (PLAN §9): no payments, no commercialization. "
        "PII redaction is the contributor's responsibility before submit."
    ),
    responses={
        201: {"description": "Co-op accepted and persisted."},
        401: {"description": "Missing, invalid, or expired session token."},
        422: {
            "description": (
                "k=2 anonymity violation OR validation error (extra fields, "
                "invalid industry, salary_range_usd > 10k chars, etc.)."
            ),
        },
    },
)
def upload_coop(
    req: CoopUploadRequest,
    conn: DbConn,
    coop_repo: Annotated[CoopRepository, Depends(get_coop_repo)],
    user_repo: Annotated[UserRepository, Depends(get_user_repo)],
    x_user_id: Annotated[str | None, Depends(get_current_user_id)] = None,
) -> CoopUploadResponse:
    if not x_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: log in and send "
                   "Authorization: Bearer <session_token> (ADR-0021)",
        )

    coop_id = f"coop-{uuid.uuid4().hex[:12]}"
    visibility_level = _derive_visibility(req)

    new_coop = CoopExperience(
        coop_id=coop_id,
        company=req.company,
        role=req.role,
        coop_term=req.coop_term,
        industry=req.industry,
        duration_months=req.duration_months,
        related_courses=req.related_courses,
        interview_summary=req.interview_summary,
        technical_questions=req.technical_questions,
        salary_range_usd=req.salary_range_usd,
        contributor_user_id=x_user_id,
        is_seed_data=False,
        visibility_level=visibility_level,
        redaction_audit=None,
    )

    # k-anonymity gate. corpus = existing + new (test_coop_schema convention:
    # the new row counts toward k). Block if (company, role, coop_term)
    # appears < 2 times in the combined set.
    existing = coop_repo.list_all()
    combined_corpus = existing + [new_coop]
    if is_uniquely_identifying(new_coop, combined_corpus, k=2):
        log.warning(
            "coop.rejected.k_anonymity",
            user_id=x_user_id,
            company=req.company,
            role=req.role,
            coop_term=req.coop_term,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Submission would be uniquely identifying "
                "(company, role, coop_term) — please generalize one field "
                "(e.g. industry bucket instead of company name) before "
                "publishing."
            ),
        )

    coop_repo.add(new_coop)
    # Give-to-get gate (PLAN §6.4): credit the contributor so higher
    # visibility tiers actually unlock. Same transaction as the insert; the
    # contributor_user_id FK guarantees the users row exists once add()
    # succeeded, so this cannot UserNotFound on any path add() survives.
    user_repo.increment_contribution_count(x_user_id)
    conn.commit()  # route owns the transaction; repos don't auto-commit
    log.info(
        "coop.accepted",
        coop_id=coop_id,
        user_id=x_user_id,
        visibility_level=visibility_level,
    )
    return CoopUploadResponse(
        coop_id=coop_id,
        accepted=True,
        visibility_level=visibility_level,
    )


@router.get(
    "",
    response_model=list[CoopOut],
    summary="List Co-op records visible to user (give-to-get)",
    description=(
        "Returns rows visible to the caller per the give-to-get gate "
        "(PLAN §6.4):\n\n"
        "- Anonymous (no token) → only `visibility_level=0` (preview) "
        "rows.\n"
        "- Authenticated → calls `CoopRepository.list_visible_to_user`, "
        "which exposes higher-tier rows in proportion to the user's own "
        "`contribution_count`.\n\n"
        "Each row is sanitized: `contributor_user_id` and `redaction_audit` "
        "are server-internal and NOT returned."
    ),
    responses={200: {"description": "List of visible Co-op records."}},
)
def list_coop(
    coop_repo: Annotated[CoopRepository, Depends(get_coop_repo)],
    x_user_id: Annotated[str | None, Depends(get_current_user_id)] = None,
) -> list[CoopOut]:
    if x_user_id:
        rows = coop_repo.list_visible_to_user(x_user_id)
    else:
        # Equivalent to contribution_count=0 (only level-0 visible).
        rows = [c for c in coop_repo.list_all() if c.visibility_level == 0]

    return [
        CoopOut(
            coop_id=c.coop_id,
            company=c.company,
            role=c.role,
            industry=c.industry.value if c.industry else None,
            coop_term=c.coop_term,
            duration_months=c.duration_months,
            related_courses=c.related_courses,
            interview_summary=c.interview_summary,
            technical_questions=c.technical_questions,
            salary_range_usd=c.salary_range_usd,
            visibility_level=c.visibility_level,
        )
        for c in rows
    ]
