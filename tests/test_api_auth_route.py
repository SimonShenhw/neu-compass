"""Tests for api.routes.auth — /auth/callback OAuth code exchange."""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from api.dependencies import get_oauth_exchange_fn
from app.auth import OAuthError
from db.user_repository import UserRepository


def _override_exchange(api_client: TestClient, fn) -> None:
    api_client.app.dependency_overrides[get_oauth_exchange_fn] = lambda: fn


# === Happy path ===


def test_callback_creates_user_on_first_login(
    api_client: TestClient, empty_db: sqlite3.Connection,
) -> None:
    def fake_exchange(code: str, *, redirect_uri: str | None = None) -> dict:
        assert code == "abc123"
        return {
            "user_id": "google-sub-1",
            "email": "alice@husky.neu.edu",
            "name": "Alice",
        }

    _override_exchange(api_client, fake_exchange)
    r = api_client.post(
        "/auth/callback",
        json={"code": "abc123"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == "google-sub-1"
    assert body["email"] == "alice@husky.neu.edu"
    assert body["display_name"] == "Alice"
    assert body["contribution_count"] == 0

    # Verify the row landed in SQLite
    user = UserRepository(empty_db).get("google-sub-1")
    assert user is not None
    assert user.domain == "husky.neu.edu"


def test_callback_refreshes_login_idempotent(
    api_client: TestClient, empty_db: sqlite3.Connection,
) -> None:
    """Second login with same user_id reuses the row + bumps last_login_at."""

    def fake_exchange(code: str, *, redirect_uri: str | None = None) -> dict:
        return {
            "user_id": "u-1",
            "email": "bob@northeastern.edu",
            "name": "Bob",
        }

    _override_exchange(api_client, fake_exchange)
    api_client.post("/auth/callback", json={"code": "first"})
    # Simulate prior contribution count change
    empty_db.execute(
        "UPDATE users SET contribution_count = 5 WHERE user_id = 'u-1'"
    )
    empty_db.commit()

    r = api_client.post("/auth/callback", json={"code": "second"})
    assert r.status_code == 200
    body = r.json()
    assert body["contribution_count"] == 5  # NOT reset to 0


def test_callback_passes_redirect_uri_through(
    api_client: TestClient, empty_db: sqlite3.Connection,
) -> None:
    captured: dict = {}

    def fake_exchange(code: str, *, redirect_uri: str | None = None) -> dict:
        captured["redirect_uri"] = redirect_uri
        return {"user_id": "u-1", "email": "x@husky.neu.edu", "name": "X"}

    _override_exchange(api_client, fake_exchange)
    api_client.post(
        "/auth/callback",
        json={"code": "x", "redirect_uri": "https://compass.example.com/oauth/cb"},
    )
    assert captured["redirect_uri"] == "https://compass.example.com/oauth/cb"


# === Failure modes ===


def test_callback_oauth_error_returns_401(api_client: TestClient) -> None:
    def boom(code: str, **kw) -> dict:
        raise OAuthError("Email domain not allowed: bad@gmail.com")

    _override_exchange(api_client, boom)
    r = api_client.post("/auth/callback", json={"code": "x"})
    assert r.status_code == 401
    assert "not allowed" in r.json()["detail"]


def test_callback_missing_code_returns_422(api_client: TestClient) -> None:
    _override_exchange(api_client, lambda c, **kw: {})
    r = api_client.post("/auth/callback", json={})
    assert r.status_code == 422


def test_callback_extra_field_rejected(api_client: TestClient) -> None:
    _override_exchange(api_client, lambda c, **kw: {"user_id": "u", "email": "a@husky.neu.edu", "name": "A"})
    r = api_client.post("/auth/callback", json={"code": "c", "rogue": "x"})
    assert r.status_code == 422
