"""Tests for app.session_tokens (ADR-0021) + the Bearer dependency."""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.session_tokens import issue_session_token, verify_session_token
from config import settings
from tests.conftest import build_test_app


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setattr(settings, "session_secret", "unit-test-secret")


def test_roundtrip() -> None:
    token = issue_session_token("u-1", "u1@husky.neu.edu")
    assert token
    payload = verify_session_token(token)
    assert payload == {"user_id": "u-1", "email": "u1@husky.neu.edu"}


def test_tampered_token_returns_none() -> None:
    token = issue_session_token("u-1", "u1@husky.neu.edu")
    assert verify_session_token(token + "x") is None
    assert verify_session_token("garbage") is None
    assert verify_session_token("") is None


def test_expired_token_returns_none(monkeypatch) -> None:
    token = issue_session_token("u-1", "u1@husky.neu.edu")
    monkeypatch.setattr(settings, "session_max_age_seconds", -1)
    assert verify_session_token(token) is None


def test_empty_secret_disables_mechanism(monkeypatch) -> None:
    """Fresh checkout without SESSION_SECRET must degrade to anonymous,
    not crash."""
    monkeypatch.setattr(settings, "session_secret", "")
    assert issue_session_token("u-1", "e") is None
    assert verify_session_token("anything") is None


def test_wrong_secret_rejected(monkeypatch) -> None:
    token = issue_session_token("u-1", "u1@husky.neu.edu")
    monkeypatch.setattr(settings, "session_secret", "a-different-secret")
    assert verify_session_token(token) is None


# === route-level: explicit bad credential is 401, never silent anonymous ===


def test_post_coop_with_garbage_bearer_is_401(
    empty_db: sqlite3.Connection,
) -> None:
    app = build_test_app(empty_db, seed=False)
    with TestClient(app) as client:
        r = client.post(
            "/coop",
            json={"company": "X", "role": "Y", "coop_term": "Summer 2025"},
            headers={"Authorization": "Bearer not-a-real-token"},
        )
    assert r.status_code == 401
    assert "session token" in r.json()["detail"].lower()


def test_get_coop_with_valid_token_resolves_user(
    empty_db: sqlite3.Connection,
) -> None:
    empty_db.execute(
        "INSERT INTO users (user_id, email, domain, contribution_count) "
        "VALUES ('u-9', 'u9@husky.neu.edu', 'husky.neu.edu', 2)"
    )
    empty_db.commit()
    app = build_test_app(empty_db, seed=False)
    token = issue_session_token("u-9", "u9@husky.neu.edu")
    with TestClient(app) as client:
        r = client.get("/coop", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
