"""Signed session tokens — replaces the trusted X-User-Id header (ADR-0021).

Why: the Week 6 stub trusted whatever X-User-Id the client sent, which made
the whole OAuth + JWT chain decorative for API authorization — anyone who
could reach the API could read level-2 (salary) co-op data or attribute
uploads to any user. Tokens are issued ONLY by POST /auth/callback after a
real Google OAuth round-trip, and verified server-side on every request.

itsdangerous URLSafeTimedSerializer (the dependency sat unused in
pyproject since Week 6): HMAC-signed, tamper-evident, with max_age expiry
checked at verification time. Not encryption — payload (user_id, email) is
readable, but those aren't secrets to their own bearer.

Dev ergonomics: empty SESSION_SECRET disables the whole mechanism (both
functions return None) so a fresh checkout degrades to anonymous browsing
instead of crashing — same spirit as the reranker-less degraded mode.
"""

from __future__ import annotations

from typing import Any

from config import settings

_SALT = "neu-compass-session"


def issue_session_token(user_id: str, email: str) -> str | None:
    """Sign a session token, or None when SESSION_SECRET is unset (dev)."""
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
