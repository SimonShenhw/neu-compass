"""POST /auth/callback — Google OAuth code exchange + user persistence.

Flow:
  Browser  → google.com/oauth (user clicks Login on Streamlit page)
           ← redirected back with ?code=XXX
  Streamlit → POST /auth/callback {code, redirect_uri}
           → exchange_code_for_token (verifies JWT signature + claims)
           → UserRepository.upsert_login (creates or refreshes the row)
           ← {user_id, email, display_name, contribution_count}
  Streamlit → state_manager.login(...)

The code-exchange and JWT verification both live in app.auth (pure-ish
helpers). This route only orchestrates + persists.

Domain whitelist enforcement (PLAN §3.5) is inside
validate_id_token_claims, called via exchange_code_for_token. This route
trusts the identity it gets back.
"""

from __future__ import annotations

from typing import Annotated, Any, Callable

import structlog
from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import DbConn, get_oauth_exchange_fn, get_user_repo
from api.models import OAuthCallbackRequest, OAuthCallbackResponse
from app.auth import OAuthError
from db.user_repository import UserRepository

router = APIRouter(prefix="/auth", tags=["auth"])

log = structlog.get_logger("neu_compass.auth")


@router.post(
    "/callback",
    response_model=OAuthCallbackResponse,
    summary="Google OAuth code → JWT verify → user upsert",
    description=(
        "Exchanges the OAuth `code` (returned by Google's redirect) for an "
        "ID token, verifies the JWT signature + claims, and upserts the "
        "user row. Returns the sanitized identity for client-side session "
        "state.\n\n"
        "**Domain whitelist** is enforced inside JWT-claim validation — "
        "non-NEU emails get 401 (PLAN §3.5: split-on-`@` exact match, NOT "
        "substring; `attacker@husky.neu.edu.evil.com` is rejected).\n\n"
        "**F1 compliance**: no payment surface, no commercialization. The "
        "Google client must be set up under the developer's personal "
        "Google Cloud project — credentials never enter version control."
    ),
    responses={
        200: {"description": "OAuth round-trip succeeded; user persisted."},
        401: {
            "description": (
                "Code exchange failed, JWT invalid, or email domain not in "
                "whitelist (`husky.neu.edu` / `northeastern.edu`)."
            ),
        },
    },
)
async def oauth_callback(
    req: OAuthCallbackRequest,
    conn: DbConn,
    user_repo: Annotated[UserRepository, Depends(get_user_repo)],
    exchange_fn: Annotated[
        Callable[..., dict[str, Any]],
        Depends(get_oauth_exchange_fn),
    ],
) -> OAuthCallbackResponse:
    try:
        identity = exchange_fn(
            req.code,
            redirect_uri=req.redirect_uri,
        )
    except OAuthError as e:
        log.info("auth.callback.rejected", reason=str(e))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        ) from e

    email = identity["email"]
    domain = email.partition("@")[2].lower()
    user = user_repo.upsert_login(
        user_id=identity["user_id"],
        email=email,
        domain=domain,
        display_name=identity.get("name") or None,
    )
    conn.commit()

    log.info(
        "auth.callback.success",
        user_id=user.user_id,
        domain=user.domain,
        contribution_count=user.contribution_count,
    )
    return OAuthCallbackResponse(
        user_id=user.user_id,
        email=user.email,
        display_name=user.display_name,
        contribution_count=user.contribution_count,
    )
