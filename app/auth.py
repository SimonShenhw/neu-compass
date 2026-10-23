"""Moved to api/google_oauth.py in R2a (2026-10-22). These are the same objects, re-exported for the Streamlit UI
until it is retired; new code imports from api.google_oauth.

中文：R2a（2026-10-22）搬到了 api/google_oauth.py。这里转发的是同一批对象，给 Streamlit 版用到它退役为止；新代码从
api.google_oauth 导入。
"""

from api.google_oauth import (
    GOOGLE_AUTHORIZE_ENDPOINT,
    GOOGLE_ISSUERS,
    GOOGLE_JWKS_URL,
    GOOGLE_TOKEN_ENDPOINT,
    OAuthError,
    authorize_url,
    exchange_code_for_token,
    is_email_allowed,
    validate_id_token_claims,
)

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
