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

GET /coop applies the give-to-get gate at FIELD level (PLAN §6.4 tier
model): every row is listed for everyone, but interview/technical fields
are stripped below tier 1 and salary below tier 2 (tier = the caller's
contribution_count, clamped to 2). Row-level filtering — the original
implementation — starved the marketplace: all seed rows carry salary
(level 2), so anonymous and fresh users saw an EMPTY list and the
give-to-get loop could never bootstrap. visibility_level still reports
the row's intrinsic tier so the UI can render "contribute to unlock"
hints for stripped fields.
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
    # A signed token can outlive its user row (7-day max_age vs. account
    # deletion); without this check the contributor_user_id FK fails as a
    # 500. Same 401 contract as /auth/me — the client clears its session.
    if user_repo.get(x_user_id) is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unknown user. Log in again.",
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
    summary="List Co-op records (give-to-get, field-level redaction)",
    description=(
        "Returns ALL rows with tier-gated FIELDS redacted server-side "
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
    responses={200: {"description": "List of Co-op records (redacted per tier)."}},
)
def list_coop(
    coop_repo: Annotated[CoopRepository, Depends(get_coop_repo)],
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
            interview_summary=c.interview_summary if tier >= 1 else None,
            technical_questions=c.technical_questions if tier >= 1 else None,
            salary_range_usd=c.salary_range_usd if tier >= 2 else None,
            visibility_level=c.visibility_level,
        )
        for c in coop_repo.list_all()
    ]
