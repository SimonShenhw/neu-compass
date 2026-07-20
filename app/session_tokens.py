"""Signed session tokens — replaces the trusted X-User-Id header (ADR-0021).

签名会话 token —— 取代原先"信任型" X-User-Id 头（ADR-0021）。

Why: the Week 6 stub trusted whatever X-User-Id the client sent, which made
the whole OAuth + JWT chain decorative for API authorization — anyone who
could reach the API could read level-2 (salary) co-op data or attribute
uploads to any user. Tokens are issued ONLY by POST /auth/callback after a
real Google OAuth round-trip, and verified server-side on every request.

原因：第 6 周的占位实现会无条件信任客户端发来的 X-User-Id，这让整条
OAuth + JWT 链条对 API 授权来说只是摆设 —— 任何能访问到 API 的人都能
读取 level-2（薪资）的 co-op 数据，或者把上传记录冒充成任意用户的。
Token 现在只由 POST /auth/callback 在一次真实的 Google OAuth 往返之后
签发，并且在每次请求时都做服务端校验。

itsdangerous URLSafeTimedSerializer (the dependency sat unused in
pyproject since Week 6): HMAC-signed, tamper-evident, with max_age expiry
checked at verification time. Not encryption — payload (user_id, email) is
readable, but those aren't secrets to their own bearer.

itsdangerous 的 URLSafeTimedSerializer（这个依赖从第 6 周起就闲置在
pyproject 里没用上）：HMAC 签名、可防篡改，校验时会检查 max_age 过期
时间。这不是加密 —— payload（user_id、email）是可读的，但对 token
持有者本人来说，这些本来就不是秘密。

Dev ergonomics: empty SESSION_SECRET disables the whole mechanism (both
functions return None) so a fresh checkout degrades to anonymous browsing
instead of crashing — same spirit as the reranker-less degraded mode.

开发体验：SESSION_SECRET 留空会禁用整套机制（两个函数都返回 None），
这样一次全新的 checkout 会降级为匿名浏览而不是直接崩溃 —— 与没有
reranker 时的降级模式是同一种精神。
"""

from __future__ import annotations

from typing import Any

from config import settings

_SALT = "neu-compass-session"


def issue_session_token(user_id: str, email: str) -> str | None:
    """Sign a session token, or None when SESSION_SECRET is unset (dev).
    签发一个签名会话 token；SESSION_SECRET 未设置时（开发环境）返回 None。"""
    if not settings.session_secret:
        return None
    from itsdangerous import URLSafeTimedSerializer  # noqa: PLC0415

    s = URLSafeTimedSerializer(settings.session_secret, salt=_SALT)
    return s.dumps({"user_id": user_id, "email": email})


def verify_session_token(token: str) -> dict[str, Any] | None:
    """Return the payload for a valid, unexpired token; None otherwise.

    None covers ALL failure modes (bad signature, expired, malformed,
    secret unset) — callers translate None into 401/anonymous; they never
    need to distinguish why.

    对于有效且未过期的 token，返回其 payload；否则返回 None。

    None 覆盖了所有失败情形（签名错误、已过期、格式不对、secret 未
    设置）—— 调用方把 None 一律翻译成 401/匿名，完全不需要区分原因。
    """
    if not settings.session_secret or not token:
        return None
    from itsdangerous import BadSignature, URLSafeTimedSerializer  # noqa: PLC0415

    s = URLSafeTimedSerializer(settings.session_secret, salt=_SALT)
    try:
        payload = s.loads(token, max_age=settings.session_max_age_seconds)
    except BadSignature:  # includes SignatureExpired
        return None
    if not isinstance(payload, dict) or "user_id" not in payload:
        return None
    return payload


__all__ = ["issue_session_token", "verify_session_token"]
