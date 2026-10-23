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

The code-exchange and JWT verification both live in api.google_oauth (pure-ish
helpers). This route only orchestrates + persists.

授权码兑换与 JWT 校验都在 api.google_oauth 里（相对纯粹的辅助函数）。本路由只
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
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from api.dependencies import (
    DbConn,
    get_current_user_id,
    get_oauth_exchange_fn,
    get_user_repo,
)
from api.models import (
    AuthMeResponse,
    DeleteAccountRequest,
    DeleteAccountResponse,
    LoginUrlResponse,
    OAuthCallbackRequest,
    OAuthCallbackResponse,
)
from api.csrf import from_web_origin, refusal
from api.session_cookie import (
    COOKIE_NAME,
    expire_session_cookie,
    expired_session_cookie_header,
    set_session_cookie,
)
from api.google_oauth import OAuthError
from api.error_fields import safe_error_fields
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
        "Google Cloud project — credentials never enter version control.\n\n"
        "**Session** (R2a): `\"session\": \"token\"` (the default) returns the "
        "signed token as `session_token`, as before. `\"session\": \"cookie\"` "
        "sets it instead as the HttpOnly cookie `__Host-nc_api_session` "
        "(Secure, Path=/, SameSite=Lax, as long as the token lasts) and returns "
        "`session_token: null`; the web front end uses this. The cookie mode "
        "must come from an allowed web origin with `X-NEU-Compass: 1`, or it "
        "gets the fixed CSRF 403 before the code is exchanged: a page elsewhere "
        "must not log the browser into an account of its choosing."
    ),
    responses={
        200: {"description": "OAuth round-trip succeeded; user persisted."},
        401: {
            "description": (
                "Code exchange failed, JWT invalid, or email domain not in "
                "whitelist (`husky.neu.edu` / `northeastern.edu`)."
            ),
        },
        403: {"description": "The cookie mode, not from an allowed web origin with `X-NEU-Compass: 1`."},
    },
)
def oauth_callback(
    req: OAuthCallbackRequest,
    request: Request,
    conn: DbConn,
    response: Response,
    user_repo: Annotated[UserRepository, Depends(get_user_repo)],
    exchange_fn: Annotated[
        Callable[..., dict[str, Any]],
        Depends(get_oauth_exchange_fn),
    ],
) -> OAuthCallbackResponse | Response:
    # Sync `def`: exchange_fn does a blocking httpx POST to Google (up to 10s
    # timeout). As `async def` that held the event loop hostage; threadpool
    # execution keeps the API responsive during a slow Google round-trip.
    # 中文：同步 def —— exchange_fn 会对 Google 发起阻塞的 httpx POST
    # （超时上限 10s）。若写成 `async def` 会把事件循环困住；线程池执行能
    # 让 API 在 Google 响应慢时依然保持响应能力。
    from config import settings  # noqa: PLC0415

    # R2a: only the web front end may log a browser in with the cookie, cookie or not; checked before the code reaches
    # Google. 中文：R2a：只有新前端能用 cookie 模式登录浏览器，不管原来带没带 cookie；在 code 交给 Google 之前查。
    if req.session == "cookie" and not from_web_origin(request, settings.web_origins):
        return refusal()
    try:
        identity = exchange_fn(
            req.code,
            redirect_uri=req.redirect_uri,
        )
    except OAuthError as e:
        log.info("auth.callback.rejected", **e.log_fields(), **safe_error_fields(e))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=e.safe_detail,
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

    # No account id: the API log rotates by size, not by time, and deleting an account cannot reach it, so a login line
    # names only the school domain (batch T, A24 L1). 中文：不记账号 ID：API 日志按大小轮转、没有时限，删账号也删不到，
    # 所以登录这一行只写学校域名。
    log.info(
        "auth.callback.success",
        domain=user.domain,
        contribution_count=user.contribution_count,
    )
    # ADR-0021: the ONLY place session tokens are minted — downstream of a
    # verified Google OAuth round-trip + domain whitelist.
    # 中文（ADR-0021）：这是唯一签发会话令牌的地方 —— 位于经过验证的 Google
    # OAuth 往返 + 域名白名单校验之后。
    from api.session_tokens import issue_session_token  # noqa: PLC0415

    token = issue_session_token(user.user_id, user.email)
    if req.session == "cookie":
        # R2a: the new front end keeps the token out of script reach; no SESSION_SECRET means no token, as before.
        # 中文：R2a：新前端让脚本碰不到令牌；没有 SESSION_SECRET 就没有令牌，和以前一样。
        if token is not None:
            set_session_cookie(response, token)
        token = None
    return OAuthCallbackResponse(
        user_id=user.user_id,
        email=user.email,
        display_name=user.display_name,
        contribution_count=user.contribution_count,
        session_token=token,
    )


@router.get(
    "/me",
    response_model=AuthMeResponse,
    summary="Identity behind the Bearer session token or the session cookie",
    description=(
        "Verifies the `Authorization: Bearer <session_token>` credential "
        "and returns the current identity from the users table. The UI "
        "calls this on page load to restore login state from a persisted "
        "cookie — the token signature + max-age are re-checked server-side "
        "on every call, so a stale or tampered cookie degrades to 401, "
        "never a forged identity.\n\n"
        "Without an Authorization header, the API's own session cookie "
        "(`__Host-nc_api_session`, set by the cookie mode of `/auth/callback`) "
        "is used instead. When that cookie no longer works (bad, expired, or "
        "its account is gone), the 401 also expires it."
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
    request: Request,
    user_id: Annotated[str | None, Depends(get_current_user_id)],
    user_repo: Annotated[UserRepository, Depends(get_user_repo)],
) -> AuthMeResponse:
    # get_current_user_id already 401s on a present-but-invalid token;
    # None here means no Authorization header, and no working session cookie.
    # A session cookie (R2a) that no longer works is expired with the 401, so the browser stops sending it.
    # 中文：get_current_user_id 已经对"存在但无效的令牌"抛出 401；
    # 这里的 None 表示没有 Authorization 请求头，也没有能用的会话 cookie。
    # 不能用的会话 cookie（R2a）随 401 一起让它过期，浏览器就不再带它了。
    expire = {"set-cookie": expired_session_cookie_header()}
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
            headers=expire if COOKIE_NAME in request.cookies else None,
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
            headers=expire if getattr(request.state, "session_from_cookie", False) else None,
        )
    return AuthMeResponse(
        user_id=user.user_id,
        email=user.email,
        display_name=user.display_name,
        contribution_count=user.contribution_count,
    )


@router.post(
    "/delete-account",
    response_model=DeleteAccountResponse,
    summary="Delete the caller's account and Co-op contributions (batch T)",
    description=(
        "Requires `Authorization: Bearer <session_token>` (or the API's session cookie, R2a) and the body "
        "`{\"confirm\": \"delete\"}`. In one transaction removes the Co-op experiences this account published (and "
        "every unlock of them); then a group it helped publish that is left with one contributor goes back to "
        "approved (k=2; no credit is taken back); then the users row, which cascades to its unlocks, planned courses, "
        "Co-op submissions and credits. query_log and saved answers never record an account and are not touched; "
        "daily backups keep a copy for up to 14 days. Afterwards the same token gets 401 from `/auth/me`. A session "
        "cookie used for the call is expired, and so is one that no longer works (with the 401). Returns per-table "
        "counts only."
    ),
    responses={
        200: {"description": "Deleted; counts of the rows removed."},
        401: {"description": "Missing, invalid or expired token, or the account no longer exists."},
        422: {"description": "The body is not exactly `{\"confirm\": \"delete\"}`."},
    },
)
def delete_account(
    req: DeleteAccountRequest,
    request: Request,
    response: Response,
    user_id: Annotated[str | None, Depends(get_current_user_id)],
    conn: DbConn,
) -> DeleteAccountResponse:
    from db.account_deletion import AccountNotFound  # noqa: PLC0415
    from db.account_deletion import delete_account as delete_rows  # noqa: PLC0415

    # A session cookie (R2a) that no longer works is expired with the 401, as /auth/me does.
    # 中文：不能用的会话 cookie（R2a）随 401 一起让它过期，和 /auth/me 一样。
    from_cookie = getattr(request.state, "session_from_cookie", False)
    expire = {"set-cookie": expired_session_cookie_header()}
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token.",
                            headers=expire if COOKIE_NAME in request.cookies else None)
    try:
        counts = delete_rows(conn, user_id)
    except AccountNotFound:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown user.",
                            headers=expire if from_cookie else None) from None
    if from_cookie:  # The session ends with the account (R2a). 中文：账号没了，会话也就结束了。
        expire_session_cookie(response)
    # Counts only, named so the log check can see every key: never the account, its email or what it wrote.
    # 中文：只记计数，逐个写出键名，日志检查才看得见：不记账号、邮箱或内容。
    log.info("account.deleted", published_experiences=counts["published_experiences"],
             unlocks_of_those=counts["unlocks_of_those"], own_unlocks=counts["own_unlocks"],
             submissions=counts["submissions"], credits=counts["credits"], planned_courses=counts["planned_courses"],
             withdrawn_from_groups=counts["withdrawn_from_groups"])
    return DeleteAccountResponse(**counts)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Expire the session cookie (R2a)",
    description=(
        "Expires the API's session cookie and answers 204, also when there is none. Bearer tokens are not revoked "
        "(they expire on their own; Streamlit logs out by dropping its copy). Like every write that carries the "
        "cookie, it must come from an allowed web origin with `X-NEU-Compass: 1`."
    ),
    responses={204: {"description": "The session cookie, if any, is expired."}},
)
def logout() -> Response:
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    expire_session_cookie(response)
    return response


@router.get(
    "/login-url",
    response_model=LoginUrlResponse,
    summary="Google's login address for the web front end (R2a)",
    description=(
        "Builds the Google OAuth address with the caller's `state`, exactly as the Streamlit login link does "
        "(`api.google_oauth.authorize_url`). The front end makes `state`, keeps it, and checks it when Google sends "
        "the browser back to `GOOGLE_OAUTH_REDIRECT_URI` with `?code=&state=`; then it posts the code to "
        "`/auth/callback` with `\"session\": \"cookie\"`. The API stores nothing here."
    ),
    responses={
        200: {"description": "The address to send the browser to."},
        422: {"description": "`state` is not 16–128 characters of A–Z, a–z, 0–9, `_` or `-`."},
        503: {"description": "Login is not configured here (no Google client ID or no SESSION_SECRET)."},
    },
)
def login_url(
    state: Annotated[str, Query(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")],
) -> LoginUrlResponse:
    from api.google_oauth import authorize_url  # noqa: PLC0415
    from config import settings  # noqa: PLC0415

    if not (settings.google_oauth_client_id and settings.session_secret):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Login is not configured.")
    return LoginUrlResponse(url=authorize_url(state_token=state))
