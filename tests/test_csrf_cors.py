"""R2a: writes that carry the session cookie must come from WEB_ORIGINS with X-NEU-Compass: 1, and CORS answers only
for WEB_ORIGINS. Synthetic data only.
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from api.session_cookie import COOKIE_NAME
from api.session_tokens import issue_session_token
from config import settings
from tests.conftest import build_test_app

ORIGIN = "https://compass.example.test"
OTHER = "https://elsewhere.example.test"
REFUSED = {"detail": "Cross-site request refused.", "error_type": "csrf_rejected", "status_code": 403}
UPLOAD = {"company": "Example Fintech Co.", "role": "Data Engineer Co-op", "coop_term": "Fall 2026"}


def make_client(conn, monkeypatch, *, origins=(ORIGIN,), seed=False):
    monkeypatch.setattr(settings, "session_secret", "synthetic-csrf-secret")
    monkeypatch.setattr(settings, "web_origins", list(origins))
    return TestClient(build_test_app(conn, seed=seed), base_url="https://testserver")


def add_user(conn, user_id="synthetic-sub-1"):
    conn.execute("INSERT INTO users (user_id, email, domain) VALUES (?, ?, 'husky.neu.edu')",
                 (user_id, f"{user_id}@husky.neu.edu"))
    conn.commit()
    return issue_session_token(user_id, f"{user_id}@husky.neu.edu")


def submissions(conn):
    return conn.execute("SELECT count(*) FROM coop_submissions").fetchone()[0]


@pytest.fixture()
def cookie_client(empty_db: sqlite3.Connection, monkeypatch):
    # The client's cookie jar files a host without a dot ("testserver") as "testserver.local", so cookies put in by
    # hand use that domain. 中文：cookie jar 把不带点的主机记成「testserver.local」，手动放的 cookie 要用这个域。
    client = make_client(empty_db, monkeypatch)
    client.cookies.set(COOKIE_NAME, add_user(empty_db), domain="testserver.local")
    with client:
        yield client


@pytest.mark.parametrize("headers", [
    {"Origin": ORIGIN},                                   # no marker. 中文：没有标记头。
    {"Origin": ORIGIN, "X-NEU-Compass": "true"},          # a marker that is not exactly 1
    {"Origin": OTHER, "X-NEU-Compass": "1"},              # another origin
    {"X-NEU-Compass": "1"},                               # no Origin at all
    {"Origin": ORIGIN + "/", "X-NEU-Compass": "1"},       # not the origin as configured
    {"Origin": "null", "X-NEU-Compass": "1"},
])
def test_a_cookie_write_without_both_signs_is_refused_and_does_nothing(cookie_client, empty_db, headers):
    response = cookie_client.post("/coop", json=UPLOAD, headers=headers)
    assert response.status_code == 403 and response.json() == REFUSED
    assert OTHER not in response.text and "elsewhere" not in response.text
    assert submissions(empty_db) == 0


def test_two_origin_headers_are_refused(cookie_client, empty_db):
    response = cookie_client.post("/coop", json=UPLOAD,
                                  headers=[("Origin", ORIGIN), ("Origin", ORIGIN), ("X-NEU-Compass", "1")])
    assert response.status_code == 403 and submissions(empty_db) == 0


def test_an_empty_authorization_header_does_not_exempt_a_cookie_write(cookie_client, empty_db):
    """get_current_user_id takes an empty header for none and uses the cookie, so the check must not skip it.
    中文：身份解析把空的 Authorization 头当作没有、转而用 cookie，所以这里不能因此免查。"""
    response = cookie_client.post("/coop", json=UPLOAD, headers={"Authorization": ""})
    assert response.status_code == 403 and submissions(empty_db) == 0


@pytest.mark.parametrize("cookie_headers", [
    lambda token: [("Cookie", f"{COOKIE_NAME} = {token}")],
    lambda token: [("Cookie", "synthetic=1"), ("Cookie", f"{COOKIE_NAME}={token}")],
], ids=["spaces_around_the_equals_sign", "in_a_second_cookie_header"])
def test_a_cookie_that_starlette_reads_is_never_missed(empty_db, monkeypatch, cookie_headers):
    with make_client(empty_db, monkeypatch) as client:
        headers = cookie_headers(add_user(empty_db))
        assert client.get("/auth/me", headers=headers).status_code == 200  # the session works. 中文：会话是有效的。
        response = client.post("/coop", json=UPLOAD, headers=headers)
        assert response.status_code == 403 and submissions(empty_db) == 0


def test_a_cookie_write_from_the_front_end_goes_through(cookie_client, empty_db):
    response = cookie_client.post("/coop", json=UPLOAD, headers={"Origin": ORIGIN, "X-NEU-Compass": "1"})
    assert response.status_code == 201 and submissions(empty_db) == 1


def test_bearer_writes_are_not_checked_even_with_the_cookie_present(cookie_client, empty_db):
    bearer = add_user(empty_db, "synthetic-sub-2")
    response = cookie_client.post("/coop", json=UPLOAD, headers={"Authorization": f"Bearer {bearer}"})
    assert response.status_code == 201


def test_reads_and_cookieless_writes_are_not_checked(empty_db, monkeypatch):
    with make_client(empty_db, monkeypatch, seed=True) as client:
        assert client.post("/search", json={"query": "graph algorithms BFS"}).status_code == 200
        client.cookies.set(COOKIE_NAME, add_user(empty_db), domain="testserver.local")
        assert client.get("/coop").status_code == 200 and client.get("/auth/me").status_code == 200


def test_an_empty_cookie_value_is_no_session(cookie_client, empty_db):
    cookie_client.cookies.set(COOKIE_NAME, "", domain="testserver.local")
    assert cookie_client.post("/auth/logout").status_code == 204


def test_without_web_origins_every_cookie_write_is_refused(empty_db, monkeypatch):
    with make_client(empty_db, monkeypatch, origins=()) as client:
        client.cookies.set(COOKIE_NAME, add_user(empty_db), domain="testserver.local")
        response = client.post("/coop", json=UPLOAD, headers={"Origin": ORIGIN, "X-NEU-Compass": "1"})
        assert response.status_code == 403 and submissions(empty_db) == 0


# === CORS ===


def test_a_preflight_from_an_allowed_origin_gets_the_cors_answer(cookie_client):
    response = cookie_client.options("/coop", headers={
        "Origin": ORIGIN, "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-neu-compass"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"
    allowed = {h.strip().lower() for h in response.headers["access-control-allow-headers"].split(",")}
    assert {"content-type", "x-neu-compass"} <= allowed
    assert response.headers["access-control-max-age"] == "600"


def test_a_preflight_from_another_origin_is_not_allowed(cookie_client):
    response = cookie_client.options("/coop", headers={
        "Origin": OTHER, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "x-neu-compass"})
    assert response.status_code == 400 and "access-control-allow-origin" not in response.headers


def test_responses_to_an_allowed_origin_expose_the_request_id(cookie_client):
    response = cookie_client.get("/coop", headers={"Origin": ORIGIN})
    assert response.headers["access-control-allow-origin"] == ORIGIN
    exposed = {h.strip().lower() for h in response.headers["access-control-expose-headers"].split(",")}
    assert {"x-request-id", "retry-after"} <= exposed and "x-request-id" in response.headers
    assert "access-control-allow-origin" not in cookie_client.get("/coop", headers={"Origin": OTHER}).headers


def test_the_refusal_itself_carries_cors_headers(cookie_client):
    response = cookie_client.post("/coop", json=UPLOAD, headers={"Origin": ORIGIN})
    assert response.status_code == 403 and response.headers["access-control-allow-origin"] == ORIGIN


def test_even_the_last_resort_500_carries_cors_headers(empty_db, monkeypatch):
    """CORS wraps the request logging, whose own 500 answers an exception that escaped the app.
    中文：CORS 包在请求日志外面，日志兜底的 500 也带 CORS 头。"""
    monkeypatch.setattr(settings, "web_origins", [ORIGIN])
    app = build_test_app(empty_db, seed=False)

    def synthetic_boom():
        raise RuntimeError("synthetic failure")

    app.add_api_route("/synthetic-boom", synthetic_boom, methods=["GET"])
    with TestClient(app, base_url="https://testserver", raise_server_exceptions=False) as client:
        response = client.get("/synthetic-boom", headers={"Origin": ORIGIN})
    assert response.status_code == 500 and response.json()["error_type"] == "internal_error"
    assert response.headers["access-control-allow-origin"] == ORIGIN and "synthetic failure" not in response.text


def test_without_web_origins_there_is_no_cors_at_all(empty_db, monkeypatch):
    """No CORS layer at all, not one that allows nobody: that one would still add headers and answer preflights.
    中文：完全没有 CORS 这一层，而不是一个谁都不放行的 CORS：那样照样会加头、会回答预检。"""
    with make_client(empty_db, monkeypatch, origins=()) as client:
        response = client.get("/coop", headers={"Origin": ORIGIN})
        assert response.status_code == 200
        assert [name for name in response.headers if name.startswith("access-control-")] == []
        preflight = client.options("/coop", headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST"})
        assert preflight.status_code == 405  # the app's own answer. 中文：应用自己的回答。
        assert [name for name in preflight.headers if name.startswith("access-control-")] == []


def test_a_refused_write_takes_no_admission_place_and_429s_carry_cors(empty_db, monkeypatch):
    """CSRF sits outside the guard, CORS outside both (R2a). 中文：跨站防护在门禁外面，CORS 在最外面。"""
    monkeypatch.setattr(settings, "request_guard_enabled", True)
    monkeypatch.setattr(settings, "request_guard_capacity", 1)
    monkeypatch.setattr(settings, "request_guard_refill_per_second", 0.01)
    with make_client(empty_db, monkeypatch, seed=True) as client:
        client.cookies.set(COOKIE_NAME, add_user(empty_db), domain="testserver.local")
        body = {"query": "graph algorithms BFS"}
        assert client.post("/search", json=body, headers={"Origin": ORIGIN}).status_code == 403
        allowed = {"Origin": ORIGIN, "X-NEU-Compass": "1"}
        assert client.post("/search", json=body, headers=allowed).status_code == 200  # the one place. 中文：唯一的名额。
        denied = client.post("/search", json=body, headers=allowed)
        assert denied.status_code == 429 and denied.headers["access-control-allow-origin"] == ORIGIN
