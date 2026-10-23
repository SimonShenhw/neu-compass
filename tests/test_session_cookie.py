"""R2a: the API's session cookie for the new web front end.

The cookie mode of /auth/callback, the cookie's attributes, Bearer before cookie, a stale cookie on public routes and
on /auth/me, logout, and account deletion. Synthetic users and secrets only; Google is the existing exchange stand-in.
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from api.dependencies import get_oauth_exchange_fn
from api.session_cookie import COOKIE_NAME
from api.session_tokens import issue_session_token, verify_session_token
from config import settings
from tests.conftest import build_test_app

ORIGIN = "https://compass.example.test"
WRITE = {"Origin": ORIGIN, "X-NEU-Compass": "1"}
SECRET = "synthetic-cookie-secret"


def identity(user_id="synthetic-sub-1", email="synthetic.one@husky.neu.edu"):
    return lambda code, *, redirect_uri=None: {"user_id": user_id, "email": email, "name": "Synthetic One"}


@pytest.fixture()
def client(empty_db: sqlite3.Connection, monkeypatch):
    monkeypatch.setattr(settings, "session_secret", SECRET)
    monkeypatch.setattr(settings, "web_origins", [ORIGIN])
    app = build_test_app(empty_db, seed=False)
    app.dependency_overrides[get_oauth_exchange_fn] = identity
    # https, so the client's cookie jar sends the Secure cookie back. 中文：用 https，cookie jar 才会带回 Secure cookie。
    with TestClient(app, base_url="https://testserver") as c:
        yield c


def set_cookie_headers(response):
    return [value for name, value in response.headers.multi_items() if name.lower() == "set-cookie"]


def one_set_cookie(response):
    headers = set_cookie_headers(response)
    assert len(headers) == 1, headers
    return headers[0]


def attributes(header):
    name_value, *rest = [part.strip() for part in header.split(";")]
    name, _, value = name_value.partition("=")
    attrs = {}
    for part in rest:
        key, _, val = part.partition("=")
        attrs[key.lower()] = val
    return name, value, attrs


def login(client, **body):
    return client.post("/auth/callback", json={"code": "synthetic-code", "session": "cookie", **body}, headers=WRITE)


def test_cookie_mode_sets_the_session_cookie_and_keeps_the_token_out_of_the_body(client):
    response = login(client)
    assert response.status_code == 200
    assert response.json() == {"user_id": "synthetic-sub-1", "email": "synthetic.one@husky.neu.edu",
                               "display_name": "Synthetic One", "contribution_count": 0, "session_token": None}
    name, value, attrs = attributes(one_set_cookie(response))
    assert name == COOKIE_NAME == "__Host-nc_api_session"
    assert verify_session_token(value)["user_id"] == "synthetic-sub-1"
    assert attrs["max-age"] == "604800" and attrs["path"] == "/" and attrs["samesite"].lower() == "lax"
    assert "httponly" in attrs and "secure" in attrs and "domain" not in attrs


def test_token_mode_is_unchanged(client):
    response = client.post("/auth/callback", json={"code": "synthetic-code"})
    assert response.status_code == 200 and set_cookie_headers(response) == []
    assert verify_session_token(response.json()["session_token"])["user_id"] == "synthetic-sub-1"


def test_cookie_mode_without_a_secret_sets_nothing(client, monkeypatch):
    monkeypatch.setattr(settings, "session_secret", "")
    response = login(client)
    assert response.status_code == 200 and response.json()["session_token"] is None
    assert set_cookie_headers(response) == []


@pytest.mark.parametrize(("headers", "origins"), [
    ({}, [ORIGIN]), ({"Origin": ORIGIN}, [ORIGIN]), ({"X-NEU-Compass": "1"}, [ORIGIN]),
    ({"Origin": "https://elsewhere.example.test", "X-NEU-Compass": "1"}, [ORIGIN]), (WRITE, []),
], ids=["no-signs", "no-marker", "no-origin", "another-origin", "no-web-origins"])
def test_the_cookie_login_only_comes_from_the_front_end(empty_db, monkeypatch, headers, origins):
    """Else a page elsewhere could log the browser into an account it chose (login CSRF). Refused before the code
    reaches Google: the exchange is never called and no account is written. 中文：不然别的网站能把浏览器登录成它选的
    账号（登录劫持）。在 code 交给 Google 之前就拒绝：不调用交换，也不写账号。"""
    calls = []

    def exchange(code, *, redirect_uri=None):
        calls.append(code)
        return {"user_id": "synthetic-sub-1", "email": "synthetic.one@husky.neu.edu", "name": "Synthetic One"}

    monkeypatch.setattr(settings, "session_secret", SECRET)
    monkeypatch.setattr(settings, "web_origins", origins)
    app = build_test_app(empty_db, seed=False)
    app.dependency_overrides[get_oauth_exchange_fn] = lambda: exchange
    with TestClient(app, base_url="https://testserver") as client:
        response = client.post("/auth/callback", json={"code": "synthetic-code", "session": "cookie"}, headers=headers)
        assert response.status_code == 403 and response.json() == {
            "detail": "Cross-site request refused.", "error_type": "csrf_rejected", "status_code": 403}
        assert set_cookie_headers(response) == [] and calls == []
        assert empty_db.execute("SELECT count(*) FROM users").fetchone()[0] == 0
        # The token mode (Streamlit, scripts) is not checked. 中文：token 模式（Streamlit、脚本）不查。
        assert client.post("/auth/callback", json={"code": "synthetic-code"}, headers=headers).status_code == 200
        assert calls == ["synthetic-code"]


@pytest.mark.parametrize("mode", ["both", "Cookie", "", None, 1])
def test_an_unknown_session_mode_is_refused(client, mode):
    response = client.post("/auth/callback", json={"code": "synthetic-code", "session": mode})
    assert response.status_code == 422 and set_cookie_headers(response) == []


def test_the_cookie_logs_the_browser_in_and_the_token_never_reaches_the_log(client):
    with capture_logs() as logs:
        response = login(client)
    token = attributes(one_set_cookie(response))[1]
    assert token not in repr(logs)
    me = client.get("/auth/me")
    assert me.status_code == 200 and me.json()["user_id"] == "synthetic-sub-1"


def test_bearer_comes_before_the_cookie(client, empty_db):
    login(client)  # the cookie names synthetic-sub-1. 中文：cookie 是 synthetic-sub-1 的。
    empty_db.execute("INSERT INTO users (user_id, email, domain) VALUES ('synthetic-sub-2', "
                     "'synthetic.two@husky.neu.edu', 'husky.neu.edu')")
    empty_db.commit()
    bearer = issue_session_token("synthetic-sub-2", "synthetic.two@husky.neu.edu")
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {bearer}"}).json()["user_id"] == "synthetic-sub-2"
    # An explicit Bearer that fails is a 401, even with a good cookie next to it. 中文：坏的 Bearer 就是 401。
    assert client.get("/auth/me", headers={"Authorization": "Bearer not-a-token"}).status_code == 401


def expired(header):
    """An expiring Set-Cookie that a browser accepts for a __Host- name: Secure, Path=/ and no Domain, or it keeps the
    cookie. 中文：浏览器只接受带 Secure、Path=/、不带 Domain 的 __Host- 过期 Set-Cookie，不然 cookie 还留着。"""
    name, value, attrs = attributes(header)
    return (name == COOKIE_NAME and value in ("", '""') and (attrs.get("max-age") == "0" or "expires" in attrs)
            and "secure" in attrs and attrs.get("path") == "/" and "domain" not in attrs)


@pytest.mark.parametrize("token", ["not-a-token", "stale"])
def test_a_stale_cookie_is_a_guest_on_public_routes_and_me_expires_it(client, monkeypatch, token):
    if token == "stale":  # a real token past its age. 中文：一个过期的真令牌。
        token = issue_session_token("synthetic-sub-1", "synthetic.one@husky.neu.edu")
        monkeypatch.setattr(settings, "session_max_age_seconds", -1)
    client.cookies.set(COOKIE_NAME, token, domain="testserver.local")  # the jar's name for "testserver"
    assert client.get("/coop").status_code == 200  # public browsing still works. 中文：公开浏览照常。
    me = client.get("/auth/me")
    assert me.status_code == 401
    assert expired(one_set_cookie(me))


def test_me_without_any_credential_touches_no_cookie(client):
    response = client.get("/auth/me")
    assert response.status_code == 401 and set_cookie_headers(response) == []


def test_the_cookie_of_a_deleted_account_is_expired_by_me(client, empty_db):
    login(client)
    empty_db.execute("DELETE FROM users WHERE user_id = 'synthetic-sub-1'")
    empty_db.commit()
    me = client.get("/auth/me")
    assert me.status_code == 401 and expired(one_set_cookie(me))


def test_logout_expires_the_cookie(client):
    login(client)
    response = client.post("/auth/logout", headers=WRITE)
    assert response.status_code == 204 and response.content == b""
    assert expired(one_set_cookie(response))
    assert client.get("/auth/me").status_code == 401


def test_logout_without_a_cookie_is_still_204(client):
    assert client.post("/auth/logout").status_code == 204


def test_deleting_the_account_with_the_cookie_ends_the_session(client):
    login(client)
    response = client.post("/auth/delete-account", json={"confirm": "delete"}, headers=WRITE)
    assert response.status_code == 200 and response.json()["deleted"] is True
    assert expired(one_set_cookie(response))
    assert client.get("/auth/me").status_code == 401


def test_deleting_with_a_bearer_leaves_cookies_alone(client):
    token = client.post("/auth/callback", json={"code": "synthetic-code"}).json()["session_token"]
    response = client.post("/auth/delete-account", json={"confirm": "delete"},
                           headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200 and set_cookie_headers(response) == []


@pytest.mark.parametrize("cookie", ["not-a-token", "gone"])
def test_deleting_with_a_cookie_that_no_longer_works_expires_it(client, empty_db, cookie):
    if cookie == "gone":  # a good token whose account is already deleted. 中文：令牌没问题，账号已经删了。
        login(client)
        empty_db.execute("DELETE FROM users WHERE user_id = 'synthetic-sub-1'")
        empty_db.commit()
    else:
        client.cookies.set(COOKIE_NAME, cookie, domain="testserver.local")
    response = client.post("/auth/delete-account", json={"confirm": "delete"}, headers=WRITE)
    assert response.status_code == 401 and expired(one_set_cookie(response))


def test_a_401_without_a_cookie_or_for_a_bearer_touches_no_cookie(client, empty_db):
    response = client.post("/auth/delete-account", json={"confirm": "delete"})
    assert response.status_code == 401 and set_cookie_headers(response) == []
    token = client.post("/auth/callback", json={"code": "synthetic-code"}).json()["session_token"]
    empty_db.execute("DELETE FROM users WHERE user_id = 'synthetic-sub-1'")
    empty_db.commit()
    bearer = {"Authorization": f"Bearer {token}"}
    for response in (client.get("/auth/me", headers=bearer),
                     client.post("/auth/delete-account", json={"confirm": "delete"}, headers=bearer)):
        assert response.status_code == 401 and set_cookie_headers(response) == []


def test_the_coop_tier_follows_the_cookie(client, empty_db):
    from db.coop_repository import CoopRepository
    from schemas.coop import CoopExperience

    CoopRepository(empty_db).add(CoopExperience(
        coop_id="coop-synthetic-salary", company="Example Quant LLC", role="Quant Developer Co-op",
        coop_term="Spring 2026", salary_range_usd="$40-45/hr", is_seed_data=True, visibility_level=2))
    empty_db.commit()
    login(client)
    assert client.get("/coop").json()[0]["salary_range_usd"] is None  # 0 contributions. 中文：没有贡献。
    empty_db.execute("UPDATE users SET contribution_count = 2 WHERE user_id = 'synthetic-sub-1'")
    empty_db.commit()
    assert client.get("/coop").json()[0]["salary_range_usd"] == "$40-45/hr"
