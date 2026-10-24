"""Google OAuth + NEU domain whitelist (PLAN §3.6 / §4.1).

Moved here from app/auth.py in R2a (2026-10-22): login belongs to the API, and the new front end has no Python side.
app/auth.py re-exports these names for the Streamlit UI until that UI is retired.

Google OAuth + NEU 域名白名单（PLAN §3.6 / §4.1）。R2a（2026-10-22）从 app/auth.py 搬到这里：登录归 API 管，新前端没有
Python 那一侧。app/auth.py 转发这些名字，给 Streamlit 版用到它退役为止。

Login flow:
  1. Streamlit page renders the URL from `authorize_url()`. User clicks,
     Google authenticates, redirects back to `google_oauth_redirect_uri`
     with `?code=...&state=...`.
  2. Callback handler (left as a Week 7 follow-up — needs a real
     OAuth-aware HTTP path; Streamlit's URL handling is limited) exchanges
     the code for an ID token via authlib.
  3. The parsed claims go through `validate_id_token_claims` which raises
     OAuthError if anything fails. Only on success do we persist to
     state_manager.login.

登录流程：
  1. Streamlit 页面渲染出 `authorize_url()` 给出的 URL。用户点击后，
     Google 完成认证，带着 `?code=...&state=...` 重定向回
     `google_oauth_redirect_uri`。
  2. 回调处理器（作为第 7 周的后续工作留待完成 —— 需要一条真正支持
     OAuth 的 HTTP 路径；Streamlit 的 URL 处理能力有限）通过 authlib
     用 code 兑换 ID token。
  3. 解析出的 claims 会经过 `validate_id_token_claims`，任何一项失败
     都会抛出 OAuthError。只有全部通过才会持久化到
     state_manager.login。

`is_email_allowed` is the security boundary that every code path MUST go
through. Substring matching (e.g. `email.endswith("husky.neu.edu")`) is
NOT acceptable — `attacker@husky.neu.edu.evil.com` would slip through.
We split on '@' and exact-match the domain part against the whitelist.

`is_email_allowed` 是每条代码路径都必须经过的安全边界。子串匹配
（例如 `email.endswith("husky.neu.edu")`）是不可接受的 ——
`attacker@husky.neu.edu.evil.com` 会从中溜过去。我们按 '@' 切分，
拿域名部分与白名单做精确匹配。

The Authlib client itself isn't constructed here; we hand back the
authorize URL so any HTTP frontend (Streamlit, FastAPI dev page, manual
curl) can drive the redirect.

Authlib 客户端本身不在这里构造；我们只是把 authorize URL 递回去，
这样任何 HTTP 前端（Streamlit、FastAPI 开发页面、手动 curl）都能
自己驱动这次重定向。
"""

from __future__ import annotations

import functools
import re
from typing import Any, Callable
from urllib.parse import urlencode

import httpx

from config import settings


GOOGLE_AUTHORIZE_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")


class OAuthError(RuntimeError):
    """Seven stable reasons; public text never includes provider text or identity.

    中文：七种稳定原因；对外文字不包含上游原文或身份信息。
    """

    MESSAGES = {
        "token_exchange_rejected": "Google token exchange failed. Please sign in again.",
        "token_endpoint_unreachable": "Could not reach Google token endpoint. Please try again.",
        "missing_id_token": "Google token response did not include a valid id_token.",
        "id_token_invalid": "ID token verification failed. Please sign in again.",
        "claims_invalid": "ID token email/sub claims are invalid.",
        "email_unverified": "Google reports email is not verified.",
        "domain_not_allowed": "Email domain not allowed. Restricted to husky.neu.edu / northeastern.edu.",
    }

    def __init__(self, message: str | None = None, *, reason: str = "claims_invalid",
                 upstream_status: int | None = None, google_error: object = None,
                 email_domain: object = None) -> None:
        self.reason = reason if reason in self.MESSAGES else "claims_invalid"
        self.safe_detail = self.MESSAGES[self.reason]
        self.upstream_status = upstream_status if type(upstream_status) is int and 100 <= upstream_status <= 599 else None
        self.google_error = google_error if isinstance(google_error, str) and re.fullmatch(r"[a-z_]{1,64}", google_error) else None
        self.email_domain = email_domain if isinstance(email_domain, str) and re.fullmatch(r"[a-z0-9.-]{1,253}", email_domain) else None
        # Preserve the existing type-only verifier diagnostic, never arbitrary legacy messages.
        # 中文：兼容既有的 verifier 类型诊断，但不保留调用方任意传入的消息。
        diagnostic = message if (self.reason == "id_token_invalid" and isinstance(message, str)
            and re.fullmatch(r"ID token verification failed: [A-Za-z_][A-Za-z0-9_]{0,63}", message)) else self.safe_detail
        super().__init__(diagnostic)

    def log_fields(self) -> dict[str, object]:
        fields: dict[str, object] = {"oauth_reason": self.reason}
        for name in ("upstream_status", "google_error", "email_domain"):
            if (value := getattr(self, name)) is not None:
                fields[name] = value
        return fields


def is_email_allowed(email: str | None) -> bool:
    """True iff email's domain (post-'@') exactly matches one in the
    whitelist (case-insensitive). Strict: must be a single '@' email,
    domain compared verbatim — no substring match.

    当且仅当 email 的域名部分（'@' 之后）与白名单中某一项精确匹配
    （大小写不敏感）时返回 True。严格模式：必须是恰好一个 '@' 的邮箱，
    域名逐字符比较 —— 不做子串匹配。"""
    if not email or email.count("@") != 1:
        return False
    _, _, domain = email.partition("@")
    domain = domain.strip().lower()
    if not domain:
        return False
    return domain in {d.strip().lower() for d in settings.allowed_email_domains}


def authorize_url(*, state_token: str = "", redirect_uri: str | None = None) -> str:
    """Build the Google OAuth 2.0 authorize URL.

    Caller is responsible for generating + verifying `state_token`
    (CSRF protection). MVP can pass an empty string in dev; production
    MUST pass a per-request random token and verify it on callback.
    `redirect_uri` defaults to GOOGLE_OAUTH_REDIRECT_URI; the caller checks any
    other value first (R2b: only the web front end's own addresses).

    构造 Google OAuth 2.0 的 authorize URL。

    生成 + 校验 `state_token`（CSRF 防护）是调用方的责任。MVP 在开发
    环境下可以传空字符串；生产环境必须为每次请求传一个随机 token，
    并在回调时校验它。`redirect_uri` 默认是 GOOGLE_OAUTH_REDIRECT_URI；
    传别的值，调用方先核对（R2b：只认新前端自己的地址）。
    """
    params: dict[str, str] = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": redirect_uri or settings.google_oauth_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "prompt": "select_account",
        # No `hd` parameter on purpose: Google only accepts ONE hosted-domain
        # value, but settings.allowed_email_domains is the multi-domain list
        # ({husky.neu.edu, northeastern.edu}). Hard-coding `hd=husky.neu.edu`
        # locks the email input UI to that suffix and breaks northeastern.edu
        # users — observed Week 7 sprint. Domain enforcement is server-side
        # in validate_id_token_claims; no security boundary lost.
        # 中文:故意不加 `hd` 参数：Google 只接受一个 hosted-domain 值，
        # 而 settings.allowed_email_domains 是个多域名列表
        # （{husky.neu.edu, northeastern.edu}）。写死 `hd=husky.neu.edu`
        # 会把邮箱输入 UI 锁死在那个后缀上，害 northeastern.edu 用户
        # 用不了 —— 第 7 周 sprint 里实际观察到过。域名强制检查在
        # validate_id_token_claims 里做服务端校验；安全边界并未削弱。
    }
    if state_token:
        params["state"] = state_token
    return f"{GOOGLE_AUTHORIZE_ENDPOINT}?{urlencode(params)}"


def validate_id_token_claims(claims: dict[str, Any]) -> dict[str, Any]:
    """Given parsed Google ID-token claims, return a sanitized identity dict
    or raise OAuthError. Pure function — no I/O.

    Required claims:
      - email + email_verified=True
      - sub (Google's stable user id)

    Domain whitelist is the only authorization check at this layer. The
    caller persists into state_manager.login on success.

    给定解析好的 Google ID-token claims，返回一个清洗过的身份字典，
    否则抛出 OAuthError。纯函数 —— 无 I/O。

    必需的 claims：
      - email + email_verified=True
      - sub（Google 的稳定用户 id）

    域名白名单是这一层唯一的授权检查。成功后由调用方持久化到
    state_manager.login。
    """
    if not isinstance(claims, dict):
        raise OAuthError("Claims payload must be an object")

    email = claims.get("email")
    if not isinstance(email, str) or not email:
        raise OAuthError("ID token missing 'email' claim")
    if not claims.get("email_verified", False):
        raise OAuthError(reason="email_unverified")
    if not is_email_allowed(email):
        domain = email.partition("@")[2].lower() if email.count("@") == 1 else None
        raise OAuthError(reason="domain_not_allowed", email_domain=domain)

    sub = claims.get("sub")
    if not sub:
        raise OAuthError("ID token missing 'sub' claim")

    return {
        "user_id": str(sub),
        "email": str(email),
        "name": claims.get("name") or "",
    }


@functools.lru_cache(maxsize=1)
def _fetch_google_jwks() -> dict[str, Any]:
    """Fetch Google's public JWKS for ID-token signature verification.

    Cached process-wide via lru_cache. Google rotates keys roughly daily;
    _verify_google_id_token clears this cache and retries once when a token
    doesn't verify against the cached set (kid miss after rotation), so a
    long-lived process doesn't lock every login out until restart.

    抓取 Google 的公开 JWKS，用于校验 ID-token 的签名。

    通过 lru_cache 做进程级缓存。Google 大约每天轮换一次密钥；当某个
    token 用缓存的密钥集合校验不过（轮换后的 kid 未命中）时，
    _verify_google_id_token 会清空这个缓存并重试一次，这样长期运行的
    进程不会一直把所有登录都拒之门外直到重启。
    """
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(GOOGLE_JWKS_URL)
        resp.raise_for_status()
        return resp.json()


def _verify_google_id_token(id_token: str) -> dict[str, Any]:
    """Decode + verify a Google-issued JWT against cached JWKS.

    Validates: signature, issuer, audience (our client_id), expiry. Returns
    a plain dict of claims for downstream domain/email checks.

    On first failure, refetches the JWKS once and retries — covers the
    "Google rotated keys since we cached them" case. A failure against
    FRESH keys is a genuinely bad token and propagates.

    解码并对照缓存的 JWKS 校验一个 Google 签发的 JWT。

    校验内容：签名、issuer、audience（我们的 client_id）、过期时间。
    返回一个普通的 claims 字典，供下游做域名/邮箱检查。

    第一次失败时，重新抓取一次 JWKS 并重试 —— 覆盖"缓存之后 Google
    又轮换了密钥"这种情形。若对着刚抓取的新密钥仍然失败，说明这个
    token 确实有问题，异常会向上传播。
    """
    from authlib.jose import JsonWebKey, jwt  # noqa: PLC0415

    def _decode(jwks: dict[str, Any]) -> dict[str, Any]:
        key_set = JsonWebKey.import_key_set(jwks)
        claims = jwt.decode(
            id_token,
            key_set,
            claims_options={
                "iss": {"essential": True, "values": list(GOOGLE_ISSUERS)},
                "aud": {
                    "essential": True,
                    "value": settings.google_oauth_client_id,
                },
            },
        )
        claims.validate()
        return dict(claims)

    try:
        return _decode(_fetch_google_jwks())
    except Exception:
        _fetch_google_jwks.cache_clear()
        return _decode(_fetch_google_jwks())


def exchange_code_for_token(
    code: str,
    *,
    redirect_uri: str | None = None,
    http_client: httpx.Client | None = None,
    id_token_verifier: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """End-to-end OAuth callback handler.

    Pipeline:
      1. POST `code` to Google token endpoint → {access_token, id_token, ...}.
      2. Decode + verify id_token (signature via JWKS, claims via authlib).
      3. validate_id_token_claims for domain whitelist + email_verified.

    Returns the sanitized identity dict {user_id, email, name}.
    Raises OAuthError with user-safe messages on any failure.

    Test injection:
      - `http_client`: pass an httpx.Client backed by a MockTransport to
        substitute the token-exchange HTTP without hitting Google.
      - `id_token_verifier`: pass a callable to bypass JWT verification
        entirely (handy when you don't want to construct a signed JWT in
        the test). Default uses `_verify_google_id_token`.

    端到端的 OAuth 回调处理器。

    流水线：
      1. 把 `code` POST 给 Google 的 token 端点 →
         {access_token, id_token, ...}。
      2. 解码 + 校验 id_token（签名走 JWKS，claims 走 authlib）。
      3. 用 validate_id_token_claims 检查域名白名单 + email_verified。

    返回清洗过的身份字典 {user_id, email, name}。
    任何失败都会抛出带用户可读消息的 OAuthError。

    测试注入点：
      - `http_client`：传一个背后接着 MockTransport 的 httpx.Client，
        用它替代真实的 token 兑换请求，不必真的打到 Google。
      - `id_token_verifier`：传一个可调用对象，完全绕过 JWT 校验
        （不想在测试里构造一个签过名的 JWT 时很好用）。默认使用
        `_verify_google_id_token`。
    """
    redirect_uri = redirect_uri or settings.google_oauth_redirect_uri
    own_client = http_client is None
    client = http_client or httpx.Client(timeout=10.0)
    try:
        try:
            resp = client.post(
                GOOGLE_TOKEN_ENDPOINT,
                data={
                    "code": code,
                    "client_id": settings.google_oauth_client_id,
                    "client_secret": settings.google_oauth_client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
        except httpx.RequestError as e:
            raise OAuthError(reason="token_endpoint_unreachable") from e
    finally:
        if own_client:
            client.close()

    if resp.status_code != 200:
        # Only the bounded OAuth error code is diagnostic; descriptions are untrusted.
        # 中文：只保留有界错误码；Google 的描述也可能包含输入，不展示或记录。
        try:
            payload = resp.json()
        except ValueError:
            payload = {}
        google_error = payload.get("error") if isinstance(payload, dict) else None
        raise OAuthError(reason="token_exchange_rejected", upstream_status=resp.status_code,
                         google_error=google_error)

    try:
        body = resp.json()
    except ValueError as exc:
        raise OAuthError(reason="missing_id_token") from exc
    id_token = body.get("id_token") if isinstance(body, dict) else None
    if not isinstance(id_token, str) or not id_token:
        raise OAuthError(reason="missing_id_token")

    verifier = id_token_verifier or _verify_google_id_token
    try:
        claims = verifier(id_token)
    except OAuthError:
        raise
    except Exception as e:
        # Type only: google-auth's messages can quote the token or its audience values. The route
        # uses safe_detail and structured fields, never this exception's text.
        # 中文：只给类型：google-auth 的消息里可能引用 token 本身或 audience 的值；路由只使用
        # safe_detail 和结构化字段，不使用这段异常文字。
        raise OAuthError(
            f"ID token verification failed: {type(e).__name__}", reason="id_token_invalid",
        ) from e

    return validate_id_token_claims(claims)


__all__ = [
    "GOOGLE_AUTHORIZE_ENDPOINT",
    "GOOGLE_ISSUERS",
    "GOOGLE_JWKS_URL",
    "GOOGLE_TOKEN_ENDPOINT",
    "OAuthError",
    "authorize_url",
    "exchange_code_for_token",
    "is_email_allowed",
    "validate_id_token_claims",
]
