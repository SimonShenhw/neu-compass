"""R2b: the local dev API (tests/support/dev_api.py) logs a browser in and out through its fake Google, and production
code never imports it. Synthetic data only.

中文：R2b：本机开发用的 API 能通过假的 Google 登录、登出，生产代码从不 import 它。只用合成数据。"""

from __future__ import annotations

import ast
import json
import re
from html import unescape
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import anyio
import pytest
from fastapi.testclient import TestClient

import api.dependencies
import api.google_oauth
from api.session_cookie import COOKIE_NAME
from config import settings
from tests.support import dev_api

ROOT = Path(__file__).resolve().parent.parent
FRONT_END = dev_api.FRONT_ENDS[0]
WRITE = {"Origin": FRONT_END, "X-NEU-Compass": "1"}
STATE = "dev-test-state-0123456789abcdef0123"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # Everything the dev API changes in this process goes back after the test. 中文：测试完把改动都还原。
    for name in dev_api.CONFIGURED:
        monkeypatch.setattr(settings, name, getattr(settings, name))
    monkeypatch.setattr(api.google_oauth, "authorize_url", api.google_oauth.authorize_url)
    app = dev_api.build_dev_app(tmp_path / "dev.sqlite3", base="https://dev-api.test")
    with TestClient(app, base_url="https://testserver") as c:
        yield c


def sign_in_links(client, front_end=FRONT_END):
    url = client.get("/auth/login-url", params={"state": STATE, "redirect_uri": f"{front_end}/"}).json()["url"]
    page = urlparse(url)
    assert f"{page.scheme}://{page.netloc}{page.path}" == "https://dev-api.test/__dev/google"
    response = client.get(f"{page.path}?{page.query}")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    return [unescape(href) for href in re.findall(r'href="([^"]+)"', response.text)]


def code_and_state(link):
    query = parse_qs(urlparse(link).query)
    return query.get("code", [None])[0], query["state"][0]


def test_the_fake_google_brings_the_browser_back_to_the_front_end(client):
    links = sign_in_links(client)
    assert all(link.startswith(f"{FRONT_END}/?") for link in links)
    codes = [code_and_state(link) for link in links]
    assert codes[:6] == [(code, STATE) for code in [*dev_api.ACCOUNTS, *dev_api.REFUSALS]]
    assert codes[6] == ("dev-student", dev_api.WRONG_STATE)
    assert parse_qs(urlparse(links[7]).query) == {"error": ["access_denied"], "state": [STATE]}


def test_a_preview_build_comes_back_to_its_own_port(client):
    preview = dev_api.FRONT_ENDS[1]
    assert all(link.startswith(f"{preview}/?") for link in sign_in_links(client, preview))


def test_a_restart_logs_everyone_out(client, tmp_path):
    first = settings.session_secret
    dev_api.configure(settings, tmp_path / "again.sqlite3")
    assert settings.session_secret != first and len(settings.session_secret) >= 32


def test_logging_in_and_out_with_the_cookie(client):
    response = client.post("/auth/callback", headers=WRITE,
                           json={"code": "dev-student", "session": "cookie", "redirect_uri": f"{FRONT_END}/"})
    assert response.status_code == 200 and response.json()["email"] == "synthetic.student@husky.neu.edu"
    assert client.cookies.get(COOKIE_NAME)
    me = client.get("/auth/me")
    assert me.status_code == 200 and me.json()["display_name"] == "Synthetic Student"
    assert client.post("/auth/logout", headers=WRITE).status_code == 204
    assert client.get("/auth/me").status_code == 401


@pytest.mark.parametrize("code", list(dev_api.REFUSALS))
def test_the_refused_codes_say_why(client, code):
    response = client.post("/auth/callback", headers=WRITE,
                           json={"code": code, "session": "cookie", "redirect_uri": f"{FRONT_END}/"})
    assert response.status_code == 401 and response.json()["reason"] == dev_api.REFUSALS[code][1]


def test_the_sign_in_page_sends_nobody_elsewhere_and_escapes_what_it_echoes(client):
    response = client.get("/__dev/google", params={"state": STATE, "redirect_uri": "https://evil.test/"})
    assert response.status_code == 400 and "evil" not in response.text
    response = client.get("/__dev/google", params={"state": '"><script>x</script>', "redirect_uri": f"{FRONT_END}/"})
    assert response.status_code == 200 and "<script>" not in response.text


def test_the_front_end_reads_the_courses_and_the_config(client):
    assert client.get("/config").json() == {"answer_feedback_enabled": False, "login_available": True}
    assert client.get("/course/c-cs-5800").json()["primary_code"] == "CS 5800"


def ask(client, query):
    response = client.post("/chat", json={"query": query, "k": 5, "allow_feedback_capture": False})
    assert response.status_code == 200
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def test_a_question_gets_the_scripted_answer_and_never_a_model(client, monkeypatch):
    def no_model(*_args, **_kwargs):
        raise AssertionError("a model was called")

    monkeypatch.setattr(dev_api, "PIECE_SECONDS", 0)
    monkeypatch.setattr(settings, "hyde_rescue", True)
    monkeypatch.setattr(api.dependencies, "generate_text_stream", no_model)
    monkeypatch.setattr("rag.hyde.rescue_expand", no_model)
    events = ask(client, "CS 5800 讲什么？")
    assert [event["type"] for event in events] == ["meta", *["token"] * len(dev_api.ANSWER), "done"]
    assert "".join(event["text"] for event in events[1:-1]) == "".join(dev_api.ANSWER)
    overrides = client.app.dependency_overrides
    assert overrides[api.dependencies.get_hyde_rescue_fn]() is None
    assert overrides[api.dependencies.get_chat_stream_fn]() is dev_api.chat_stream


@pytest.mark.parametrize(("word", "types", "error_type"), [
    ("dev:model-error", ["meta", "token", "token", "error", "done"], "upstream_error"),
    ("dev:no-answer", ["meta", "error", "done"], "no_answer"),
    ("dev:daily-limit", ["meta", "error", "done"], "daily_limit"),
])
def test_a_question_can_ask_for_a_failure(client, monkeypatch, word, types, error_type):
    monkeypatch.setattr(dev_api, "PIECE_SECONDS", 0)
    events = ask(client, f"CS 5800 {word}")
    assert [event["type"] for event in events] == types
    assert events[-2]["error_type"] == error_type


def test_a_question_can_ask_for_a_stream_without_done(client, monkeypatch):
    monkeypatch.setattr(dev_api, "PIECE_SECONDS", 0)
    assert [event["type"] for event in ask(client, "CS 5800 dev:no-done")] == ["meta", "token", "token"]


@pytest.mark.parametrize(("word", "ends"), [("dev:cut", False), ("dev:no-done", True)])
def test_a_cut_never_ends_the_response_and_no_done_ends_it_early(word, ends):
    async def five_lines(scope, receive, send):
        await receive()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        for number in range(5):
            await send({"type": "http.response.body", "body": f"{number}\n".encode(), "more_body": True})
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    sent = []

    async def receive():
        return {"type": "http.request", "body": json.dumps({"query": f"x {word}"}).encode(), "more_body": False}

    async def send(message):
        sent.append(message)

    anyio.run(dev_api.CutChat(five_lines), {"type": "http", "path": "/chat"}, receive, send)
    bodies = [message for message in sent if message["type"] == "http.response.body"]
    assert b"".join(message["body"] for message in bodies) == b"0\n1\n2\n"
    assert bodies[-1]["more_body"] is not ends


def test_a_stall_is_longer_than_the_front_end_waits(monkeypatch):
    slept = []
    monkeypatch.setattr(dev_api.time, "sleep", slept.append)
    assert list(dev_api.chat_stream("x dev:stall")) == list(dev_api.ANSWER)
    assert slept[2] == dev_api.STALL_SECONDS > 30
    assert slept[:2] + slept[3:] == [dev_api.PIECE_SECONDS] * (len(dev_api.ANSWER) - 1)


def imported_names(path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):  # `from tests import support` counts as tests.support. 中文：也算。
            yield from (f"{node.module or ''}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)


def test_production_code_never_imports_the_dev_api():
    """What is deployed imports nothing from tests; the tools in scripts/ may use test helpers, never the dev API.
    中文：部署的代码不 import tests 里的任何东西；scripts/ 里的工具可以用测试的辅助函数，但不碰开发用的 API。"""
    for package in ("api", "app", "config", "db", "llm", "rag", "schemas"):
        for path in (ROOT / package).rglob("*.py"):
            assert not any(name.startswith("tests") for name in imported_names(path)), path
    for path in (ROOT / "scripts").rglob("*.py"):
        assert not any(name.startswith("tests.support") for name in imported_names(path)), path
