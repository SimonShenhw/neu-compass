"""R2a: GET /privacy, GET /config, GET /auth/login-url, the moved auth modules and WEB_ORIGINS. Synthetic data only."""

from __future__ import annotations

import itertools
import json
import logging
import sqlite3
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from config import settings
from tests.conftest import build_test_app

STATE = "synthetic-state-0123456789abcdef"
# Google's client ID and secret and a SESSION_SECRET: login needs all three. 中文：登录三样都要有。
LOGIN_SETTINGS = {"google_oauth_client_id": "synthetic-client-id",
                  "google_oauth_client_secret": "synthetic-client-secret", "session_secret": "synthetic-secret"}
# Every way of leaving at least one of them out. 中文：至少缺一样的每一种组合。
WITHOUT_LOGIN = [dict(zip(LOGIN_SETTINGS, values, strict=True))
                 for values in itertools.product(*[(value, "") for value in LOGIN_SETTINGS.values()]) if not all(values)]


def missing_names(missing):
    return "missing-" + "+".join(name for name, value in missing.items() if not value) if missing else "all-set"


@pytest.fixture()
def client(empty_db: sqlite3.Connection):
    with TestClient(build_test_app(empty_db, seed=False)) as c:
        yield c


@pytest.fixture()
def login_settings(monkeypatch):
    for name, value in LOGIN_SETTINGS.items():
        monkeypatch.setattr(settings, name, value)


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
        "sections": [{"heading": h, "sentences": s} for h, s in privacy_sections(settings, web=True)],
        "delete_what": DELETE_WHAT,
        "query_log_notice": QUERY_LOG_NOTICE_BASE,
        "capture_notice": capture_notice(days) if feedback else None,
    }
    text = repr(body)
    assert (f"原文保存 {days} 天" in text) is bool(days)
    assert ((contact or "@@") in text) is bool(contact)


def test_only_the_web_page_says_course_pages_stay_in_the_browser_history(client):
    # R3e, R4c: each course page and each program page of the web front end has its own address; the Streamlit page
    # never puts either in its address, so its sections stay as they were.
    # 中文：新前端每门课、每个培养方案一个网址；Streamlit 页的网址里都没有，它的文字不变。
    from api.privacy_text import privacy_sections

    sections = {section["heading"]: section["sentences"] for section in client.get("/privacy").json()["sections"]}
    assert any("/course/CS-6140" in sentence and "/programs/cs-ms" in sentence and "浏览器历史" in sentence
               for sentence in sections["记了什么"])
    assert not any("浏览器历史" in sentence for _, sentences in privacy_sections(settings) for sentence in sentences)
    # It is the last sentence of 「记了什么」, and the rest is Streamlit's word for word (review B32).
    # 中文：它是「记了什么」的最后一句，别的和 Streamlit 一字不差。
    streamlit = {heading: list(sentences) for heading, sentences in privacy_sections(settings)}
    assert sections["记了什么"][:-1] == streamlit["记了什么"] and "浏览器历史" in sections["记了什么"][-1]
    assert {h: s for h, s in sections.items() if h != "记了什么"} == {
        h: s for h, s in streamlit.items() if h != "记了什么"}


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


@pytest.mark.parametrize("missing", [{}, *WITHOUT_LOGIN], ids=missing_names)
def test_config_says_whether_login_works(client, login_settings, monkeypatch, missing):
    """Without the client secret every callback would fail at Google, so login is not available (A25 N4).
    中文：没有 client secret，每次回调都会在 Google 那边失败，所以不算能登录。"""
    for name, value in missing.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(settings, "answer_feedback_enabled", True)
    assert client.get("/config").json() == {"answer_feedback_enabled": True, "login_available": not missing}
    monkeypatch.setattr(settings, "answer_feedback_enabled", False)
    assert client.get("/config").json()["answer_feedback_enabled"] is False


def test_login_url_is_googles_address_with_the_callers_state(client, login_settings, monkeypatch):
    monkeypatch.setattr(settings, "google_oauth_redirect_uri", "https://compass.example.test/")
    response = client.get("/auth/login-url", params={"state": STATE})
    assert response.status_code == 200
    url = urlparse(response.json()["url"])
    query = parse_qs(url.query)
    assert (url.scheme, url.netloc) == ("https", "accounts.google.com")
    assert query["state"] == [STATE] and query["client_id"] == ["synthetic-client-id"]
    assert query["redirect_uri"] == ["https://compass.example.test/"]
    assert "synthetic-client-secret" not in response.text and "synthetic-secret" not in response.text


@pytest.mark.parametrize("state", ["a" * 16, "Z9" * 64, "synthetic_state_0123456789", "_-" * 8],
                         ids=["16", "128", "underscore", "only-punctuation"])
def test_login_url_takes_every_state_the_contract_allows(client, login_settings, state):
    """16–128 of A–Z, a–z, 0–9, `_` and `-`: R2b makes states to this (base64url uses `_`) (B25 L2).
    中文：16–128 个 A–Z、a–z、0–9、`_`、`-`：R2b 照这个生成 state（base64url 里有 `_`）。"""
    response = client.get("/auth/login-url", params={"state": state})
    assert response.status_code == 200
    assert parse_qs(urlparse(response.json()["url"]).query)["state"] == [state]


@pytest.mark.parametrize("state", ["short", "x" * 15, "x" * 129, "synthetic state with spaces",
                                   "synthetic/state/0123456789", "synthetic-state-<b>-0123456"])
def test_login_url_refuses_a_bad_state_without_echoing_it(client, login_settings, state):
    response = client.get("/auth/login-url", params={"state": state})
    assert response.status_code == 422 and state not in response.text


def test_login_url_needs_the_state(client, login_settings):
    assert client.get("/auth/login-url").status_code == 422


FRONT_ENDS = ["http://127.0.0.1:5173", "https://compass.example.test", "https://beta.example.test:8443"]
REDIRECT_REFUSED = {"detail": "redirect_uri must be the web front end's own address.", "error_type": "invalid_input",
                    "status_code": 422}


def test_login_url_sends_google_back_to_the_front_ends_own_address(client, login_settings, monkeypatch):
    """R2b: beta and local development log in on their own address, which the front end names. Without it, the
    configured address, as before. 中文：R2b：beta 和本机开发在自己的地址上登录，由前端说；不说就用配置的地址，和以前一样。"""
    monkeypatch.setattr(settings, "web_origins", FRONT_ENDS)
    monkeypatch.setattr(settings, "google_oauth_redirect_uri", "https://streamlit.example.test/")
    for origin in FRONT_ENDS:
        response = client.get("/auth/login-url", params={"state": STATE, "redirect_uri": f"{origin}/"})
        assert response.status_code == 200, origin
        query = parse_qs(urlparse(response.json()["url"]).query)
        assert query["redirect_uri"] == [f"{origin}/"] and query["state"] == [STATE]
    response = client.get("/auth/login-url", params={"state": STATE})
    assert parse_qs(urlparse(response.json()["url"]).query)["redirect_uri"] == ["https://streamlit.example.test/"]


@pytest.mark.parametrize("redirect_uri", [
    "https://compass.example.test", "https://compass.example.test/x", "https://compass.example.test//",
    "https://compass.example.test/?next=1", "https://compass.example.test/#top", "http://compass.example.test/",
    "HTTPS://compass.example.test/", "https://compass.example.test.evil.test/", "https://evil.test/",
    "https://compass.example.test:443/", "https://streamlit.example.test/", "",
])
def test_login_url_refuses_any_other_address_without_echoing_it(client, login_settings, monkeypatch, redirect_uri):
    """Only an origin in WEB_ORIGINS and `/`: Google checks the address against its own list, but a page elsewhere
    must not get a code sent to an address this API never chose. 中文：只认 WEB_ORIGINS 里的来源加 `/`：Google 也会对照
    自己的名单，但不能让 code 被送到这个 API 没选过的地址。"""
    monkeypatch.setattr(settings, "web_origins", ["https://compass.example.test"])
    monkeypatch.setattr(settings, "google_oauth_redirect_uri", "https://streamlit.example.test/")
    response = client.get("/auth/login-url", params={"state": STATE, "redirect_uri": redirect_uri})
    assert response.status_code == 422 and response.json() == REDIRECT_REFUSED


def test_login_url_takes_no_redirect_without_web_origins(client, login_settings, monkeypatch):
    monkeypatch.setattr(settings, "web_origins", [])
    response = client.get("/auth/login-url", params={"state": STATE, "redirect_uri": "http://127.0.0.1:5173/"})
    assert response.status_code == 422 and response.json() == REDIRECT_REFUSED


def test_login_url_without_login_is_503_whatever_the_address(client, monkeypatch):
    monkeypatch.setattr(settings, "google_oauth_client_id", "")
    response = client.get("/auth/login-url", params={"state": STATE, "redirect_uri": "https://evil.test/"})
    assert response.status_code == 503


def test_login_url_refuses_an_address_over_2048_characters_with_the_request(client, monkeypatch):
    """The length limit of api_contract.md is checked with the rest of the request, ahead of the 503 for a missing
    login, and the address is not echoed. 中文：api_contract.md 写的长度上限和请求的其他部分一起查，先于没配置登录的 503，
    也不回显地址。"""
    monkeypatch.setattr(settings, "google_oauth_client_id", "")
    address = "https://evil.test/" + "a" * (2049 - len("https://evil.test/"))
    response = client.get("/auth/login-url", params={"state": STATE, "redirect_uri": address})
    assert response.status_code == 422 and "evil" not in response.text
    assert client.get("/auth/login-url", params={"state": STATE, "redirect_uri": address[:2048]}).status_code == 503


@pytest.mark.parametrize("missing", WITHOUT_LOGIN, ids=missing_names)
def test_login_url_is_unavailable_without_google_or_a_secret(client, monkeypatch, missing):
    """A public route: the whole body is pinned, so no setting's name or value can slip into it (B25 L3).
    中文：公开接口：整个返回体都钉住，任何设置的名字或值都混不进去。"""
    for name, value in missing.items():
        monkeypatch.setattr(settings, name, value)
    response = client.get("/auth/login-url", params={"state": STATE})
    assert response.status_code == 503
    assert response.json() == {"detail": "Login is not configured.", "error_type": "service_unavailable",
                               "status_code": 503}


@pytest.mark.parametrize(("path", "logged"), [("/auth/login-url?state=" + STATE, "/auth/login-url"),
                                              ("/auth/login-url/?state=" + STATE, "/auth/login-url/")])
def test_the_login_state_stays_out_of_the_access_log(path, logged):
    """Uvicorn's access line would carry the query; the state stays the front end's own until Google sends it back
    (A25 N3). Other paths keep theirs (tests/test_plan_draft_review.py). 中文：uvicorn 的访问日志本来会带上查询串；
    state 在 Google 送回来以前只该前端自己知道。别的路径照旧保留查询串。"""
    from api.logging import _COURSE_READ_ACCESS_FILTER

    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 0, '%s - "%s %s HTTP/%s" %d',
                               ("synthetic", "GET", path, "1.1", 200), None)
    assert _COURSE_READ_ACCESS_FILTER.filter(record)
    assert record.args == ("synthetic", "GET", logged, "1.1", 200) and STATE not in record.getMessage()


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
                                   '["https://"]', '["compass.example.test"]', '["https://a.example.test:123456"]',
                                   # what no browser sends as Origin (A25 N2). 中文：浏览器不会这样发 Origin。
                                   '["https://compass.example.test:443"]', '["http://compass.example.test:80"]',
                                   '["https://compass.example.test:0"]', '["https://compass.example.test:65536"]',
                                   '["https://compass.example.test:99999"]', '["https://compass.example.test:08443"]',
                                   '["https://-compass.example.test"]', '["https://compass-.example.test"]',
                                   '["https://compass.-example.test"]', '["https://compass.example.test."]'])
def test_web_origins_takes_plain_lowercase_origins_only(monkeypatch, value):
    from pydantic import ValidationError

    from config.settings import Settings

    monkeypatch.setenv("WEB_ORIGINS", value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_web_origins_reads_a_json_list(monkeypatch):
    """Without the working directory's .env, which a developer may have set (B25 N6). 中文：不读当前目录的 .env。"""
    from config.settings import Settings

    origins = ["http://127.0.0.1:5173", "https://compass.example.test", "https://compass.example.test:8443",
               "http://localhost:65535", "http://localhost:1", "https://a-b.example.test",
               "http://compass.example.test:443", "https://compass.example.test:80"]
    monkeypatch.setenv("WEB_ORIGINS", json.dumps(origins))
    assert Settings(_env_file=None).web_origins == origins
    monkeypatch.setenv("WEB_ORIGINS", "[]")
    assert Settings(_env_file=None).web_origins == []
    monkeypatch.delenv("WEB_ORIGINS")
    assert Settings(_env_file=None).web_origins == []


def test_an_empty_web_origins_line_stops_the_api(monkeypatch):
    """`WEB_ORIGINS=` with nothing after it is not a JSON list: the API does not start, as .env.example says (A25 N2).
    中文：`WEB_ORIGINS=` 后面什么都不写不是 JSON 列表，API 起不来，和 .env.example 说的一样。"""
    from pydantic_settings import SettingsError

    from config.settings import Settings

    monkeypatch.setenv("WEB_ORIGINS", "")
    with pytest.raises(SettingsError):
        Settings(_env_file=None)
