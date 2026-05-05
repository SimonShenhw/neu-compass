"""Google OAuth + NEU domain whitelist (PLAN §3.6 / §4.1).

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

`is_email_allowed` is the security boundary that every code path MUST go
through. Substring matching (e.g. `email.endswith("husky.neu.edu")`) is
NOT acceptable — `attacker@husky.neu.edu.evil.com` would slip through.
We split on '@' and exact-match the domain part against the whitelist.

The Authlib client itself isn't constructed here; we hand back the
authorize URL so any HTTP frontend (Streamlit, FastAPI dev page, manual
curl) can drive the redirect.
"""

from __future__ import annotations

import functools
from typing import Any, Callable
from urllib.parse import urlencode

import httpx

from config import settings


GOOGLE_AUTHORIZE_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")


class OAuthError(RuntimeError):
    """Login refused. Message is safe to surface to the user."""


def is_email_allowed(email: str | None) -> bool:
    """True iff email's domain (post-'@') exactly matches one in the
    whitelist (case-insensitive). Strict: must be a single '@' email,
    domain compared verbatim — no substring match."""
    if not email or email.count("@") != 1:
        return False
    _, _, domain = email.partition("@")
    domain = domain.strip().lower()
    if not domain:
        return False
    return domain in {d.strip().lower() for d in settings.allowed_email_domains}


def authorize_url(*, state_token: str = "") -> str:
    """Build the Google OAuth 2.0 authorize URL.

    Caller is responsible for generating + verifying `state_token`
    (CSRF protection). MVP can pass an empty string in dev; production
    MUST pass a per-request random token and verify it on callback.
    """
    params: dict[str, str] = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": settings.google_oauth_redirect_uri,
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
    """
    if not isinstance(claims, dict):
        raise OAuthError("Claims payload must be an object")

    email = claims.get("email")
    if not email:
        raise OAuthError("ID token missing 'email' claim")
    if not claims.get("email_verified", False):
        raise OAuthError("Google reports email is not verified")
    if not is_email_allowed(email):
        raise OAuthError(
            f"Email domain not allowed: {email}. "
            f"NEU-Compass is open to {', '.join(settings.allowed_email_domains)} only."
        )

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

    Cached process-wide via lru_cache; the keys rotate roughly daily but
    Google honors old kid values long enough that one fetch per process is
    fine for MVP. Production should refresh on signature failure.
    """
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(GOOGLE_JWKS_URL)
        resp.raise_for_status()
        return resp.json()


def _verify_google_id_token(id_token: str) -> dict[str, Any]:
    """Decode + verify a Google-issued JWT against cached JWKS.

    Validates: signature, issuer, audience (our client_id), expiry. Returns
    a plain dict of claims for downstream domain/email checks.
    """
    from authlib.jose import JsonWebKey, jwt  # noqa: PLC0415

    jwks = _fetch_google_jwks()
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
            raise OAuthError(
                f"Could not reach Google token endpoint: {type(e).__name__}"
            ) from e
    finally:
        if own_client:
            client.close()

    if resp.status_code != 200:
        # Google returns JSON {error, error_description} on 4xx; surface the
        # description if present (safe — it's their text, not user input).
        try:
            payload = resp.json()
        except Exception:
            payload = {}
        detail = payload.get("error_description") or payload.get("error") or "(no detail)"
        raise OAuthError(
            f"Google token exchange failed (HTTP {resp.status_code}): {detail}"
        )

    body = resp.json()
    id_token = body.get("id_token")
    if not id_token:
        raise OAuthError("Google token response did not include id_token")

    verifier = id_token_verifier or _verify_google_id_token
    try:
        claims = verifier(id_token)
    except OAuthError:
        raise
    except Exception as e:
        raise OAuthError(
            f"ID token verification failed: {type(e).__name__}: {e}"
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
