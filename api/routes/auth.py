"""POST /auth/callback — Google OAuth code exchange + user persistence.

POST /auth/callback —— Google OAuth 授权码兑换 + 用户持久化。

Flow:
  Browser  → google.com/oauth (user clicks Login on Streamlit page)
           ← redirected back with ?code=XXX
  Streamlit → POST /auth/callback {code, redirect_uri}
           → exchange_code_for_token (verifies JWT signature + claims)
           → UserRepository.upsert_login (creates or refreshes the row)
           ← {user_id, email, display_name, contribution_count}
  Streamlit → state_manager.login(...)

流程：浏览器跳转到 google.com/oauth（用户在 Streamlit 页面点击登录）→
带 ?code=XXX 跳回；Streamlit 调用 POST /auth/callback，传
{code, redirect_uri}；exchange_code_for_token 校验 JWT 签名与声明；
UserRepository.upsert_login 创建或刷新该用户行；返回 {user_id, email,
display_name, contribution_count}；Streamlit 再调用 state_manager.login(...)。

The code-exchange and JWT verification both live in app.auth (pure-ish
helpers). This route only orchestrates + persists.

授权码兑换与 JWT 校验都在 app.auth 里（相对纯粹的辅助函数）。本路由只
负责编排与持久化。

Domain whitelist enforcement (PLAN §3.5) is inside
validate_id_token_claims, called via exchange_code_for_token. This route
trusts the identity it gets back.

域名白名单校验（PLAN §3.5）在 validate_id_token_claims 内部完成，经由
exchange_code_for_token 调用。本路由信任它返回的身份信息。
"""

from __future__ import annotations

from typing import Annotated, Any, Callable

import structlog
from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import (
    DbConn,
    get_current_user_id,
    get_oauth_exchange_fn,
    get_user_repo,
)
from api.models import (
    AuthMeResponse,
    OAuthCallbackRequest,
    OAuthCallbackResponse,
)
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
def oauth_callback(
    req: OAuthCallbackRequest,
    conn: DbConn,
    user_repo: Annotated[UserRepository, Depends(get_user_repo)],
    exchange_fn: Annotated[
        Callable[..., dict[str, Any]],
        Depends(get_oauth_exchange_fn),
    ],
) -> OAuthCallbackResponse:
    # Sync `def`: exchange_fn does a blocking httpx POST to Google (up to 10s
    # timeout). As `async def` that held the event loop hostage; threadpool
    # execution keeps the API responsive during a slow Google round-trip.
    # 中文：同步 def —— exchange_fn 会对 Google 发起阻塞的 httpx POST
    # （超时上限 10s）。若写成 `async def` 会把事件循环困住；线程池执行能
    # 让 API 在 Google 响应慢时依然保持响应能力。
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
    # ADR-0021: the ONLY place session tokens are minted — downstream of a
    # verified Google OAuth round-trip + domain whitelist.
    # 中文（ADR-0021）：这是唯一签发会话令牌的地方 —— 位于经过验证的 Google
    # OAuth 往返 + 域名白名单校验之后。
    from app.session_tokens import issue_session_token  # noqa: PLC0415

    return OAuthCallbackResponse(
        user_id=user.user_id,
        email=user.email,
        display_name=user.display_name,
        contribution_count=user.contribution_count,
        session_token=issue_session_token(user.user_id, user.email),
    )


@router.get(
    "/me",
    response_model=AuthMeResponse,
    summary="Identity behind the Bearer session token",
    description=(
        "Verifies the `Authorization: Bearer <session_token>` credential "
        "and returns the current identity from the users table. The UI "
        "calls this on page load to restore login state from a persisted "
        "cookie — the token signature + max-age are re-checked server-side "
        "on every call, so a stale or tampered cookie degrades to 401, "
        "never a forged identity."
    ),
    responses={
        200: {"description": "Token valid; identity returned."},
        401: {
            "description": (
                "Missing, invalid, or expired token — or the token's user "
                "row no longer exists."
            ),
        },
    },
)
def auth_me(
    user_id: Annotated[str | None, Depends(get_current_user_id)],
    user_repo: Annotated[UserRepository, Depends(get_user_repo)],
) -> AuthMeResponse:
    # get_current_user_id already 401s on a present-but-invalid token;
    # None here means no Authorization header at all.
    # 中文：get_current_user_id 已经对"存在但无效的令牌"抛出 401；
    # 这里的 None 表示压根没有 Authorization 请求头。
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
        )
    user = user_repo.get(user_id)
    if user is None:
        # Token outlived the user row (account deleted) — same contract as
        # an expired token: the client clears its cookie and re-logs-in.
        # 中文：令牌的存活时间超过了用户行（账号已被删除）—— 与令牌过期
        # 采用相同约定：客户端清空 cookie 并重新登录。
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unknown user.",
        )
    return AuthMeResponse(
        user_id=user.user_id,
        email=user.email,
        display_name=user.display_name,
        contribution_count=user.contribution_count,
    )
