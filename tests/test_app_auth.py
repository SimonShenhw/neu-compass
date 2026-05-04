"""Tests for app.auth — pure helpers (no Google round-trip)."""

from __future__ import annotations

import pytest

from app.auth import (
    GOOGLE_AUTHORIZE_ENDPOINT,
    OAuthError,
    authorize_url,
    is_email_allowed,
    validate_id_token_claims,
)


# === is_email_allowed ===


def test_husky_email_allowed() -> None:
    assert is_email_allowed("alice@husky.neu.edu") is True


def test_neu_alumni_email_allowed() -> None:
    assert is_email_allowed("bob@northeastern.edu") is True


def test_case_insensitive() -> None:
    assert is_email_allowed("Alice@HUSKY.NEU.EDU") is True


def test_external_domain_rejected() -> None:
    assert is_email_allowed("alice@gmail.com") is False


def test_substring_attack_rejected() -> None:
    """The classic 'attacker@husky.neu.edu.evil.com' bypass must be blocked.
    is_email_allowed splits on '@' and exact-matches the domain part."""
    assert is_email_allowed("attacker@husky.neu.edu.evil.com") is False


def test_no_at_symbol_rejected() -> None:
    assert is_email_allowed("not-an-email") is False


def test_multiple_at_rejected() -> None:
    """RFC-permitted-but-rare double-@ form goes through stricter handling
    (just refuse it; we don't need to support edge-case email syntax)."""
    assert is_email_allowed("a@b@husky.neu.edu") is False


def test_empty_email_rejected() -> None:
    assert is_email_allowed("") is False
    assert is_email_allowed(None) is False


def test_whitespace_in_domain_handled() -> None:
    assert is_email_allowed("a@  husky.neu.edu  ") is True


# === authorize_url ===


def test_authorize_url_includes_required_params() -> None:
    url = authorize_url()
    assert url.startswith(GOOGLE_AUTHORIZE_ENDPOINT)
    assert "response_type=code" in url
    assert "scope=openid+email+profile" in url
    assert "redirect_uri=" in url
    assert "client_id=" in url


def test_authorize_url_state_token_round_trips() -> None:
    url = authorize_url(state_token="csrf-abc-123")
    assert "state=csrf-abc-123" in url


def test_authorize_url_omits_state_when_empty() -> None:
    url = authorize_url(state_token="")
    assert "state=" not in url


# === validate_id_token_claims ===


def _claims(**overrides) -> dict:
    base = {
        "sub": "google-sub-1",
        "email": "alice@husky.neu.edu",
        "email_verified": True,
        "name": "Alice",
    }
    base.update(overrides)
    return base


def test_valid_claims_return_sanitized_identity() -> None:
    out = validate_id_token_claims(_claims())
    assert out == {
        "user_id": "google-sub-1",
        "email": "alice@husky.neu.edu",
        "name": "Alice",
    }


def test_missing_email_raises() -> None:
    with pytest.raises(OAuthError, match="email"):
        validate_id_token_claims(_claims(email=None))


def test_unverified_email_raises() -> None:
    with pytest.raises(OAuthError, match="not verified"):
        validate_id_token_claims(_claims(email_verified=False))


def test_external_domain_raises() -> None:
    with pytest.raises(OAuthError, match="not allowed"):
        validate_id_token_claims(_claims(email="alice@gmail.com"))


def test_missing_sub_raises() -> None:
    """Without a stable sub claim we can't persist the user."""
    claims = _claims()
    claims.pop("sub")
    with pytest.raises(OAuthError, match="sub"):
        validate_id_token_claims(claims)


def test_non_dict_payload_raises() -> None:
    with pytest.raises(OAuthError):
        validate_id_token_claims("not a dict")  # type: ignore[arg-type]


# === exchange_code_for_token (mocked HTTP + injected verifier) ===


import httpx  # noqa: E402

from app.auth import exchange_code_for_token


def _mock_token_endpoint(payload: dict, *, status_code: int = 200,
                         captured: dict | None = None) -> httpx.Client:
    """Return an httpx.Client whose POST returns the canned payload."""
    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured["url"] = str(request.url)
            captured["body"] = dict(
                pair.split("=", 1) for pair in request.content.decode().split("&")
            )
        return httpx.Response(status_code, json=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_exchange_code_returns_sanitized_identity() -> None:
    """Happy path: token endpoint returns id_token; verifier returns claims;
    validate_id_token_claims sanitizes."""
    http = _mock_token_endpoint({"id_token": "fake.jwt.token"})
    fake_verifier = lambda t: {  # noqa: E731
        "sub": "g-sub-1",
        "email": "alice@husky.neu.edu",
        "email_verified": True,
        "name": "Alice",
    }
    with http:
        identity = exchange_code_for_token(
            "fake-code",
            http_client=http,
            id_token_verifier=fake_verifier,
        )
    assert identity == {
        "user_id": "g-sub-1",
        "email": "alice@husky.neu.edu",
        "name": "Alice",
    }


def test_exchange_code_posts_correct_grant() -> None:
    captured: dict = {}
    http = _mock_token_endpoint(
        {"id_token": "x"}, captured=captured,
    )
    with http:
        exchange_code_for_token(
            "abc",
            http_client=http,
            id_token_verifier=lambda t: {  # any valid claims
                "sub": "s", "email": "a@husky.neu.edu",
                "email_verified": True, "name": "A",
            },
        )
    assert captured["url"] == "https://oauth2.googleapis.com/token"
    assert captured["body"]["code"] == "abc"
    assert captured["body"]["grant_type"] == "authorization_code"


def test_exchange_code_4xx_raises_with_detail() -> None:
    http = _mock_token_endpoint(
        {"error": "invalid_grant", "error_description": "Code expired"},
        status_code=400,
    )
    with http:
        with pytest.raises(OAuthError, match="Code expired"):
            exchange_code_for_token("bad-code", http_client=http)


def test_exchange_code_missing_id_token_raises() -> None:
    """Token response without id_token (e.g. only access_token) → OAuthError."""
    http = _mock_token_endpoint({"access_token": "x"})  # no id_token field
    with http:
        with pytest.raises(OAuthError, match="id_token"):
            exchange_code_for_token("c", http_client=http)


def test_exchange_code_propagates_validate_failure() -> None:
    """If verified claims fail the domain whitelist, OAuthError surfaces
    from validate_id_token_claims unchanged."""
    http = _mock_token_endpoint({"id_token": "fake"})
    fake_verifier = lambda t: {  # noqa: E731
        "sub": "g-1",
        "email": "external@gmail.com",  # NOT in whitelist
        "email_verified": True,
        "name": "External",
    }
    with http:
        with pytest.raises(OAuthError, match="not allowed"):
            exchange_code_for_token(
                "c", http_client=http, id_token_verifier=fake_verifier,
            )


def test_exchange_code_verifier_exception_wraps_to_oauth_error() -> None:
    """Non-OAuthError exception from the JWT verifier must surface as
    OAuthError (so callers only need one except clause)."""
    http = _mock_token_endpoint({"id_token": "x"})

    def bad_verifier(t: str) -> dict:
        raise ValueError("bad signature")

    with http:
        with pytest.raises(OAuthError, match="ID token verification failed"):
            exchange_code_for_token("c", http_client=http,
                                    id_token_verifier=bad_verifier)


def test_exchange_code_network_error_raises_oauth_error() -> None:
    """httpx.RequestError (DNS / connect failures) wraps to OAuthError too."""
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Name resolution failed")

    http = httpx.Client(transport=httpx.MockTransport(boom))
    with http:
        with pytest.raises(OAuthError, match="Could not reach Google"):
            exchange_code_for_token("c", http_client=http)
