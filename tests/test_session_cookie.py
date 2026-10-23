"""R2a: the API's session cookie for the new web front end.

The cookie mode of /auth/callback, the cookie's attributes, Bearer before cookie, a stale cookie on public routes and
on /auth/me, logout, account deletion, and the private Cache-Control on answers that depend on who asks. Synthetic
users and secrets only; Google is the existing exchange stand-in.
"""

from __future__ import annotations

import json
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
REFUSED = {"detail": "Cross-site request refused.", "error_type": "csrf_rejected", "status_code": 403}
PRIVATE = "private, no-store"


def identity(user_id="synthetic-sub-1", email="synthetic.one@husky.neu.edu"):
    return lambda code, *, redirect_uri=None: {"user_id": user_id, "email": email, "name": "Synthetic One"}


def counting_exchange(calls):
    """The Google stand-in, noting each code it is given. 中文：Google 的替身，记下每次拿到的 code。"""
    def exchange(code, *, redirect_uri=None):
        calls.append(code)
        return {"user_id": "synthetic-sub-1", "email": "synthetic.one@husky.neu.edu", "name": "Synthetic One"}

    return exchange


def add_user(conn, user_id):
    conn.execute("INSERT INTO users (user_id, email, domain) VALUES (?, ?, 'husky.neu.edu')",
                 (user_id, f"{user_id}@husky.neu.edu"))
    conn.commit()
    return issue_session_token(user_id, f"{user_id}@husky.neu.edu")


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


def logged_in(client):
    """Log in with the cookie and check the jar now holds it, so a test about the cookie cannot pass without one
    (B25 L1). 中文：用 cookie 登录，并确认 cookie jar 里真有它；讲 cookie 的测试不会在没有 cookie 时也通过。"""
    response = login(client)
    assert response.status_code == 200
    token = attributes(one_set_cookie(response))[1]
    assert client.cookies.get(COOKIE_NAME) == token
    return token


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
    monkeypatch.setattr(settings, "session_secret", SECRET)
    monkeypatch.setattr(settings, "web_origins", origins)
    app = build_test_app(empty_db, seed=False)
    app.dependency_overrides[get_oauth_exchange_fn] = lambda: counting_exchange(calls)
    with TestClient(app, base_url="https://testserver") as client:
        response = client.post("/auth/callback", json={"code": "synthetic-code", "session": "cookie"}, headers=headers)
        assert response.status_code == 403 and response.json() == REFUSED
        assert set_cookie_headers(response) == [] and calls == []
        assert empty_db.execute("SELECT count(*) FROM users").fetchone()[0] == 0
        # The token mode (Streamlit, scripts) is not checked. 中文：token 模式（Streamlit、脚本）不查。
        assert client.post("/auth/callback", json={"code": "synthetic-code"}, headers=headers).status_code == 200
        assert calls == ["synthetic-code"]


def test_the_cookie_login_takes_only_the_front_ends_own_address(empty_db, monkeypatch):
    """R2b: the code goes back to Google with the address it was sent to, which must be a web front end's own; checked
    before the code reaches Google, so nothing is exchanged or written. The token mode is not checked (Streamlit).
    中文：R2b：code 要带着 Google 当初送回的地址再交给 Google，这个地址必须是新前端自己的；在 code 交给 Google 之前查，
    所以什么也不交换、不写。token 模式不查（Streamlit 用）。"""
    seen = []

    def exchange(code, *, redirect_uri=None):
        seen.append(redirect_uri)
        return {"user_id": "synthetic-sub-1", "email": "synthetic.one@husky.neu.edu", "name": "Synthetic One"}

    monkeypatch.setattr(settings, "session_secret", SECRET)
    monkeypatch.setattr(settings, "web_origins", [ORIGIN])
    app = build_test_app(empty_db, seed=False)
    app.dependency_overrides[get_oauth_exchange_fn] = lambda: exchange
    with TestClient(app, base_url="https://testserver") as client:
        for address in [ORIGIN, f"{ORIGIN}/x", f"{ORIGIN}//", "https://elsewhere.example.test/", ""]:
            response = client.post("/auth/callback", headers=WRITE,
                                   json={"code": "synthetic-code", "session": "cookie", "redirect_uri": address})
            assert response.status_code == 422, address
            assert response.json() == {"detail": "redirect_uri must be the web front end's own address.",
                                       "error_type": "invalid_input", "status_code": 422}
            assert set_cookie_headers(response) == []
        assert seen == [] and empty_db.execute("SELECT count(*) FROM users").fetchone()[0] == 0
        response = client.post("/auth/callback", headers=WRITE,
                               json={"code": "synthetic-code", "session": "cookie", "redirect_uri": f"{ORIGIN}/"})
        assert response.status_code == 200 and seen == [f"{ORIGIN}/"]
        assert len(set_cookie_headers(response)) == 1
        # Without the cookie it just set: a write that carries the cookie must come from the front end (R2a).
        # 中文：去掉刚设的 cookie：带 cookie 的写请求必须来自前端（R2a）。
        client.cookies.clear()
        response = client.post("/auth/callback", json={"code": "synthetic-code", "redirect_uri": "https://other.test/"})
        assert response.status_code == 200 and seen[-1] == "https://other.test/"


@pytest.mark.parametrize("content_type", [None, "text/plain"], ids=["no-content-type", "text-plain"])
@pytest.mark.parametrize("session", ["token", "cookie"])
def test_a_login_body_not_sent_as_json_is_never_read(empty_db, monkeypatch, content_type, session):
    """A page elsewhere can send these two without a CORS preflight, so FastAPI's strict content type (written out in
    create_app) must leave them unread, even from the front end's own origin; the origin check is the second barrier
    (A25 L2). 中文：别的网站不用过 CORS 预检就能发这两种，所以 FastAPI 的严格 Content-Type（create_app 里明写了）不能
    读它们，从前端自己的来源发来也不读；来源检查是第二道。"""
    calls = []
    monkeypatch.setattr(settings, "session_secret", SECRET)
    monkeypatch.setattr(settings, "web_origins", [ORIGIN])
    app = build_test_app(empty_db, seed=False)
    app.dependency_overrides[get_oauth_exchange_fn] = lambda: counting_exchange(calls)
    body = json.dumps({"code": "synthetic-code", "session": session}).encode("utf-8")
    headers = {**WRITE, **({"Content-Type": content_type} if content_type else {})}
    with TestClient(app, base_url="https://testserver") as client:
        response = client.post("/auth/callback", content=body, headers=headers)
        assert response.status_code == 422 and set_cookie_headers(response) == [] and calls == []
        # The same bytes as JSON log in. 中文：同样的字节按 JSON 发，就能登录。
        sent = client.post("/auth/callback", content=body, headers={**WRITE, "Content-Type": "application/json"})
        assert sent.status_code == 200 and calls == ["synthetic-code"]


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
    logged_in(client)  # the cookie names synthetic-sub-1. 中文：cookie 是 synthetic-sub-1 的。
    assert client.get("/auth/me").json()["user_id"] == "synthetic-sub-1"
    bearer = add_user(empty_db, "synthetic-sub-2")
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {bearer}"}).json()["user_id"] == "synthetic-sub-2"
    # An explicit Bearer that fails is a 401, even with a good cookie next to it. 中文：坏的 Bearer 就是 401。
    assert client.get("/auth/me", headers={"Authorization": "Bearer not-a-token"}).status_code == 401


@pytest.mark.parametrize("header", ["Basic c3ludGhldGljOnNlY3JldA==", "Bearer", "synthetic-token"])
def test_any_other_authorization_header_is_the_credential_and_fails(client, header):
    """A non-empty Authorization header is what identity reads, as the CSRF check does, so the cookie next to it is not
    used: else a write with `Basic …` would ride the cookie unchecked (B25 L4). The 401 leaves the cookie alone.
    中文：非空的 Authorization 头就是身份解析认的凭证，和跨站检查一样，旁边的 cookie 不用：不然带 `Basic …` 的写请求
    就能不经检查地借着 cookie 过去。这个 401 也不动 cookie。"""
    logged_in(client)
    response = client.get("/auth/me", headers={"Authorization": header})
    assert response.status_code == 401 and set_cookie_headers(response) == []
    assert client.get("/auth/me").json()["user_id"] == "synthetic-sub-1"


def test_an_empty_authorization_header_is_no_credential(client):
    """It falls through to the cookie, as in the CSRF check, which therefore checks such a write (B25 L4).
    中文：空的头不算凭证，转而用 cookie，和跨站检查一样（所以那边照样要查）。"""
    logged_in(client)
    response = client.get("/auth/me", headers={"Authorization": ""})
    assert response.status_code == 200 and response.json()["user_id"] == "synthetic-sub-1"


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
    logged_in(client)
    empty_db.execute("DELETE FROM users WHERE user_id = 'synthetic-sub-1'")
    empty_db.commit()
    me = client.get("/auth/me")
    assert me.status_code == 401 and expired(one_set_cookie(me))


def test_logout_expires_the_cookie(client):
    logged_in(client)
    assert client.get("/auth/me").status_code == 200
    response = client.post("/auth/logout", headers=WRITE)
    assert response.status_code == 204 and response.content == b""
    assert expired(one_set_cookie(response))
    assert COOKIE_NAME not in client.cookies and client.get("/auth/me").status_code == 401


def test_logout_from_the_front_end_without_a_cookie_is_still_204(client):
    response = client.post("/auth/logout", headers=WRITE)
    assert response.status_code == 204 and expired(one_set_cookie(response))


@pytest.mark.parametrize("with_cookie", [False, True], ids=["no-cookie", "cookie"])
@pytest.mark.parametrize("headers", [
    {}, {"Origin": ORIGIN}, {"X-NEU-Compass": "1"}, {"Origin": "https://elsewhere.example.test", "X-NEU-Compass": "1"},
    {"Origin": "null", "X-NEU-Compass": "1"},
], ids=["no-signs", "no-marker", "no-origin", "another-origin", "null-origin"])
def test_only_the_front_end_can_log_the_browser_out(client, headers, with_cookie):
    """A form posted from another site arrives without the SameSite=Lax cookie, so the CSRF middleware lets it by; the
    expiring header would still drop the cookie, so logout checks by itself and expires nothing (A25 L1).
    中文：别的网站提交的表单不带 SameSite=Lax 的 cookie，跨站防护中间件不拦它；可回答里让 cookie 过期的头照样会删掉
    cookie，所以登出自己查，不合格就什么也不过期。"""
    if with_cookie:
        logged_in(client)
    response = client.post("/auth/logout", headers=headers)
    assert response.status_code == 403 and response.json() == REFUSED
    assert set_cookie_headers(response) == []
    if with_cookie:  # still logged in. 中文：还是登录状态。
        assert client.get("/auth/me").json()["user_id"] == "synthetic-sub-1"


def test_deleting_the_account_with_the_cookie_ends_the_session(client):
    logged_in(client)
    response = client.post("/auth/delete-account", json={"confirm": "delete"}, headers=WRITE)
    assert response.status_code == 200 and response.json()["deleted"] is True
    assert expired(one_set_cookie(response))
    assert client.get("/auth/me").status_code == 401


def test_deleting_with_a_bearer_leaves_the_cookie_alone(client, empty_db):
    """The cookie in the jar is another account's; deleting with a Bearer must not end that session (B25 L1).
    中文：jar 里的 cookie 是另一个账号的；用 Bearer 删号不能结束那个会话。"""
    logged_in(client)
    bearer = add_user(empty_db, "synthetic-sub-2")
    response = client.post("/auth/delete-account", json={"confirm": "delete"},
                           headers={"Authorization": f"Bearer {bearer}"})
    assert response.status_code == 200 and set_cookie_headers(response) == []
    assert client.get("/auth/me").json()["user_id"] == "synthetic-sub-1"


@pytest.mark.parametrize("cookie", ["not-a-token", "gone"])
def test_deleting_with_a_cookie_that_no_longer_works_expires_it(client, empty_db, cookie):
    if cookie == "gone":  # a good token whose account is already deleted. 中文：令牌没问题，账号已经删了。
        logged_in(client)
        empty_db.execute("DELETE FROM users WHERE user_id = 'synthetic-sub-1'")
        empty_db.commit()
    else:
        client.cookies.set(COOKIE_NAME, cookie, domain="testserver.local")
    response = client.post("/auth/delete-account", json={"confirm": "delete"}, headers=WRITE)
    assert response.status_code == 401 and expired(one_set_cookie(response))


def test_a_401_without_a_cookie_touches_no_cookie(client):
    response = client.post("/auth/delete-account", json={"confirm": "delete"})
    assert response.status_code == 401 and set_cookie_headers(response) == []


def test_a_401_for_a_bearer_leaves_the_cookie_alone(client, empty_db):
    """A Bearer whose account is gone gets 401 from both routes, and the cookie next to it (another account's) is not
    expired (B25 L1). 中文：账号已经不在的 Bearer 在两个接口都是 401，旁边的 cookie（另一个账号的）不过期。"""
    logged_in(client)
    bearer = {"Authorization": f"Bearer {add_user(empty_db, 'synthetic-sub-2')}"}
    empty_db.execute("DELETE FROM users WHERE user_id = 'synthetic-sub-2'")
    empty_db.commit()
    for response in (client.get("/auth/me", headers=bearer),
                     client.post("/auth/delete-account", json={"confirm": "delete"}, headers=bearer)):
        assert response.status_code == 401 and set_cookie_headers(response) == []
    assert client.get("/auth/me").json()["user_id"] == "synthetic-sub-1"


def test_the_coop_tier_follows_the_cookie(client, empty_db):
    from db.coop_repository import CoopRepository
    from schemas.coop import CoopExperience

    CoopRepository(empty_db).add(CoopExperience(
        coop_id="coop-synthetic-salary", company="Example Quant LLC", role="Quant Developer Co-op",
        coop_term="Spring 2026", salary_range_usd="$40-45/hr", is_seed_data=True, visibility_level=2))
    empty_db.commit()
    logged_in(client)
    assert client.get("/coop").json()[0]["salary_range_usd"] is None  # 0 contributions. 中文：没有贡献。
    empty_db.execute("UPDATE users SET contribution_count = 2 WHERE user_id = 'synthetic-sub-1'")
    empty_db.commit()
    assert client.get("/coop").json()[0]["salary_range_usd"] == "$40-45/hr"


def test_answers_that_depend_on_who_asks_are_private(client):
    """RFC 9111 keeps shared caches off answers to `Authorization`, not to `Cookie`: every route that reads identity
    says `private, no-store` itself, the guest's answer and the 401s too, so a cache can neither give one student's tier
    to another nor the guest view to a member. Answers that are the same for everyone, cookie or not, are left alone
    (A25 L3). 中文：RFC 9111 只禁止共享缓存复用带 `Authorization` 的回答，不管 `Cookie`：读身份的接口都自己写上
    `private, no-store`，游客的回答和 401 也写；对谁都一样的回答，带不带 cookie 都不动。"""
    for response in (client.get("/coop"), client.get("/auth/me"),  # a guest. 中文：游客。
                     client.post("/auth/delete-account", json={"confirm": "delete"})):
        assert response.headers["cache-control"] == PRIVATE
    logged_in(client)
    for response in (client.get("/coop"), client.get("/auth/me"),
                     client.get("/auth/me", headers={"Authorization": "Bearer not-a-token"})):
        assert response.headers["cache-control"] == PRIVATE
    for path in ("/privacy", "/config", "/health"):
        assert "cache-control" not in client.get(path).headers, path
