"""R2a: GET /privacy, GET /config, GET /auth/login-url, the moved auth modules and WEB_ORIGINS. Synthetic data only."""

from __future__ import annotations

import sqlite3
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from config import settings
from tests.conftest import build_test_app

STATE = "synthetic-state-0123456789abcdef"


@pytest.fixture()
def client(empty_db: sqlite3.Connection):
    with TestClient(build_test_app(empty_db, seed=False)) as c:
        yield c


@pytest.mark.parametrize(("days", "feedback", "contact"), [
    (90, True, "synthetic.student@northeastern.edu"), (0, True, None), (30, False, None),
])
def test_privacy_is_built_from_the_apis_own_settings(client, monkeypatch, days, feedback, contact):
    from api.privacy_text import DELETE_WHAT, INTRO, QUERY_LOG_NOTICE_BASE, capture_notice, privacy_sections

    monkeypatch.setattr(settings, "query_log_retention_days", days)
    monkeypatch.setattr(settings, "answer_feedback_enabled", feedback)
    monkeypatch.setattr(settings, "privacy_contact_email", contact)
    body = client.get("/privacy").json()
    assert body == {
        "intro": INTRO,
        "sections": [{"heading": h, "sentences": s} for h, s in privacy_sections(settings)],
        "delete_what": DELETE_WHAT,
        "query_log_notice": QUERY_LOG_NOTICE_BASE,
        "capture_notice": capture_notice(days) if feedback else None,
    }
    text = repr(body)
    assert (f"原文保存 {days} 天" in text) is bool(days)
    assert ((contact or "@@") in text) is bool(contact)


def test_the_notice_has_no_streamlit_layout_words(client):
    notice = client.get("/privacy").json()["query_log_notice"]
    assert "左侧" not in notice and "🔒" not in notice and notice.endswith("秘密。")


def test_streamlit_shows_the_same_words():
    from api import privacy_text
    from app import answer_feedback_view, privacy_view

    assert privacy_view.privacy_sections is privacy_text.privacy_sections
    assert privacy_view.DELETE_WHAT is privacy_text.DELETE_WHAT and privacy_view.BACKUP_COPIES == 14
    assert answer_feedback_view.capture_notice is privacy_text.capture_notice
    assert answer_feedback_view.QUERY_LOG_NOTICE == (privacy_text.QUERY_LOG_NOTICE_BASE
                                                    + "留多久、怎么删，见左侧「🔒 数据与隐私」。")


@pytest.mark.parametrize(("client_id", "secret", "available"), [
    ("synthetic-client-id", "synthetic-secret", True), ("", "synthetic-secret", False),
    ("synthetic-client-id", "", False), ("", "", False),
])
def test_config_says_whether_login_works(client, monkeypatch, client_id, secret, available):
    monkeypatch.setattr(settings, "google_oauth_client_id", client_id)
    monkeypatch.setattr(settings, "session_secret", secret)
    monkeypatch.setattr(settings, "answer_feedback_enabled", True)
    assert client.get("/config").json() == {"answer_feedback_enabled": True, "login_available": available}
    monkeypatch.setattr(settings, "answer_feedback_enabled", False)
    assert client.get("/config").json()["answer_feedback_enabled"] is False


def test_login_url_is_googles_address_with_the_callers_state(client, monkeypatch):
    monkeypatch.setattr(settings, "google_oauth_client_id", "synthetic-client-id")
    monkeypatch.setattr(settings, "session_secret", "synthetic-secret")
    monkeypatch.setattr(settings, "google_oauth_redirect_uri", "https://compass.example.test/")
    response = client.get("/auth/login-url", params={"state": STATE})
    assert response.status_code == 200
    url = urlparse(response.json()["url"])
    query = parse_qs(url.query)
    assert (url.scheme, url.netloc) == ("https", "accounts.google.com")
    assert query["state"] == [STATE] and query["client_id"] == ["synthetic-client-id"]
    assert query["redirect_uri"] == ["https://compass.example.test/"]


@pytest.mark.parametrize("state", ["short", "x" * 129, "synthetic state with spaces", "synthetic/state/0123456789",
                                   "synthetic-state-<b>-0123456"])
def test_login_url_refuses_a_bad_state_without_echoing_it(client, monkeypatch, state):
    monkeypatch.setattr(settings, "google_oauth_client_id", "synthetic-client-id")
    monkeypatch.setattr(settings, "session_secret", "synthetic-secret")
    response = client.get("/auth/login-url", params={"state": state})
    assert response.status_code == 422 and state not in response.text


def test_login_url_needs_the_state(client, monkeypatch):
    monkeypatch.setattr(settings, "google_oauth_client_id", "synthetic-client-id")
    monkeypatch.setattr(settings, "session_secret", "synthetic-secret")
    assert client.get("/auth/login-url").status_code == 422


@pytest.mark.parametrize(("client_id", "secret"), [("", "synthetic-secret"), ("synthetic-client-id", "")])
def test_login_url_is_unavailable_without_google_or_a_secret(client, monkeypatch, client_id, secret):
    monkeypatch.setattr(settings, "google_oauth_client_id", client_id)
    monkeypatch.setattr(settings, "session_secret", secret)
    response = client.get("/auth/login-url", params={"state": STATE})
    assert response.status_code == 503 and response.json()["error_type"] == "service_unavailable"


def test_the_moved_modules_are_the_same_objects():
    import api.google_oauth
    import api.session_tokens
    import app.auth
    import app.session_tokens

    for name in app.auth.__all__:
        assert getattr(app.auth, name) is getattr(api.google_oauth, name), name
    assert set(app.auth.__all__) == set(api.google_oauth.__all__)
    for name in ("issue_session_token", "verify_session_token"):
        assert getattr(app.session_tokens, name) is getattr(api.session_tokens, name)


def test_the_api_no_longer_imports_the_ui_auth_modules():
    """Deleting app/ after the switch must not break the API (R0). 中文：切换以后删 app/ 不能让 API 坏掉。"""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "api"
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("app"), f"{path.name} imports {node.module}"
            if isinstance(node, ast.Import):
                assert not any(alias.name.startswith("app") for alias in node.names), path.name


@pytest.mark.parametrize("value", ['["*"]', '["https://compass.example.test/"]', '["https://compass.example.test/x"]',
                                   '["HTTPS://compass.example.test"]', '["https://Compass.example.test"]',
                                   '["ftp://compass.example.test"]',
                                   '["https://"]', '["compass.example.test"]', '["https://a.example.test:123456"]'])
def test_web_origins_takes_plain_lowercase_origins_only(monkeypatch, value):
    from pydantic import ValidationError

    from config.settings import Settings

    monkeypatch.setenv("WEB_ORIGINS", value)
    with pytest.raises(ValidationError):
        Settings()


def test_web_origins_reads_a_json_list(monkeypatch):
    from config.settings import Settings

    monkeypatch.setenv("WEB_ORIGINS", '["http://127.0.0.1:5173", "https://compass.example.test"]')
    assert Settings().web_origins == ["http://127.0.0.1:5173", "https://compass.example.test"]
    monkeypatch.delenv("WEB_ORIGINS")
    assert Settings().web_origins == []
