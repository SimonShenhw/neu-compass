"""R2b: the local dev API (tests/support/dev_api.py) logs a browser in and out through its fake Google, and production
code never imports it. Synthetic data only.

中文：R2b：本机开发用的 API 能通过假的 Google 登录、登出，生产代码从不 import 它。只用合成数据。"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
import subprocess
import sys
import tomllib
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
def settings_back(monkeypatch):
    # Everything the dev API changes in this process goes back after the test. 中文：测试完把改动都还原。
    for name in dev_api.pinned(settings):
        monkeypatch.setattr(settings, name, getattr(settings, name))
    monkeypatch.setattr(api.google_oauth, "authorize_url", api.google_oauth.authorize_url)


@pytest.fixture()
def client(tmp_path, settings_back):
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


def test_a_restart_logs_everyone_out(client):
    client.post("/auth/callback", headers=WRITE,
                json={"code": "dev-student", "session": "cookie", "redirect_uri": f"{FRONT_END}/"})
    assert client.get("/auth/me").status_code == 200
    first = settings.session_secret
    dev_api.configure(settings, Path(settings.sqlite_path))
    assert settings.session_secret != first and len(settings.session_secret) >= 32
    assert client.get("/auth/me").status_code == 401


def test_settings_start_from_the_codes_defaults(settings_back, tmp_path):
    """Whatever .env or the environment says (a request limit, a log level) changes nothing here; only the Gemini key,
    which has no default, is left alone. 中文：.env 或环境变量（限流、日志级别）在这里都不起作用；只有没有默认值的
    Gemini key 不动。"""
    fields = type(settings).model_fields
    settings.request_guard_enabled = True
    settings.log_level = "DEBUG"
    dev_api.configure(settings, tmp_path / "dev.sqlite3")
    assert settings.request_guard_enabled is fields["request_guard_enabled"].default is False
    assert settings.log_level == fields["log_level"].default != "DEBUG"
    assert set(fields) - set(dev_api.pinned(settings)) == {"gemini_api_key"}


def test_a_setting_the_routes_copy_on_import_starts_from_its_default_too(tmp_path):
    """api/routes/common.py copies rerank_pool_size when it is first imported, which in the dev API's own process
    happens inside build_dev_app; a fresh process shows whether the reset came first (B26). 中文：api/routes/common.py
    第一次被 import 时就拷走 rerank_pool_size，在开发 API 自己的进程里这发生在 build_dev_app 里面；新开一个进程才看得出复位
    是不是在它之前（B26）。"""
    script = (
        "import sys\n"
        "from pathlib import Path\n"
        "from tests.support import dev_api\n"
        "dev_api.build_dev_app(Path(sys.argv[1]), base='https://dev-api.test')\n"
        "import api.routes.chat, api.routes.common, api.routes.search\n"
        "from config import settings\n"
        "field = type(settings).model_fields['rerank_pool_size']\n"
        "print('pool', field.get_default(call_default_factory=True), api.routes.common.RERANK_POOL_SIZE,\n"
        "      api.routes.chat.RERANK_POOL_SIZE, api.routes.search.RERANK_POOL_SIZE)\n"
    )
    done = subprocess.run([sys.executable, "-c", script, str(tmp_path / "dev.sqlite3")], cwd=ROOT,
                          env={**os.environ, "RERANK_POOL_SIZE": "3"}, capture_output=True, text=True, timeout=300,
                          check=False)
    assert done.returncode == 0, done.stderr[-2000:]
    # Log lines may share stdout; the answer is the line the script printed. 中文：日志也可能写到 stdout，只看脚本打的那行。
    [line] = [line for line in done.stdout.splitlines() if line.startswith("pool ")]
    default, *copies = line.split()[1:]
    assert default != "3" and copies == [default] * 3


def test_the_access_log_is_filtered_as_in_production(settings_back, tmp_path):
    access = logging.getLogger("uvicorn.access")
    for installed in list(access.filters):  # Whatever an earlier test installed. 中文：之前的测试装上的。
        access.removeFilter(installed)
    dev_api.build_dev_app(tmp_path / "dev.sqlite3", base="https://dev-api.test")
    # The login address (production's filter) and the sign-in page Google is replaced by (the dev API's own) both
    # carry the state. 中文：登录地址（生产的过滤器）和代替 Google 的登录页（开发 API 自己的）都带着 state。
    for target, kept in ((f"/auth/login-url?state={STATE}", "/auth/login-url"),
                         (f"/__dev/google?state={STATE}&redirect_uri=x", "/__dev/google")):
        record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 0, '%s - "%s %s HTTP/%s" %d',
                                   ("127.0.0.1:50000", "GET", target, "1.1", 200), None)
        assert access.filter(record)
        assert STATE not in record.getMessage() and f"GET {kept} HTTP" in record.getMessage()


def test_the_dev_api_listens_on_this_machine_only(settings_back, monkeypatch, capsys):
    import uvicorn  # noqa: PLC0415

    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **options: calls.append(options))
    assert dev_api.main(["--port", "8123"]) == 0
    assert calls == [{"host": "127.0.0.1", "port": 8123, "log_level": "info"}]
    assert "http://127.0.0.1:8123" in capsys.readouterr().out


def test_the_front_ends_are_the_dev_server_and_the_preview():
    """The hosts and ports of web/vite.config.ts, on 127.0.0.1 and never localhost: one host name keeps the page and
    this API one site for the browser. 中文：和 web/vite.config.ts 的主机、端口一样，用 127.0.0.1、不用 localhost：
    同一个主机名，浏览器才把页面和这个 API 算作同一个站点。"""
    config = (ROOT / "web" / "vite.config.ts").read_text(encoding="utf-8")
    port = {name: re.search(rf"{name}: \{{ host: '127\.0\.0\.1', port: (\d+),", config).group(1)
            for name in ("server", "preview")}
    assert dev_api.FRONT_ENDS == (f"http://127.0.0.1:{port['server']}", f"http://127.0.0.1:{port['preview']}")
    assert dev_api.HOST == "127.0.0.1"


def test_a_code_the_sign_in_page_never_gave_is_refused_as_google_would():
    with pytest.raises(api.google_oauth.OAuthError) as refused:
        dev_api.exchange("not-a-dev-code")
    assert refused.value.reason == "token_exchange_rejected"


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
    """What is deployed (the wheel's packages, read from pyproject.toml) imports nothing from tests; the tools in
    scripts/ may use test helpers, never the dev API. 中文：部署的代码（wheel 里的包，从 pyproject.toml 读）不 import
    tests 里的任何东西；scripts/ 里的工具可以用测试的辅助函数，但不碰开发用的 API。"""
    wheel = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["hatch"]["build"]["targets"]
    packages = wheel["wheel"]["packages"]
    assert {"api", "app", "scrapers"} <= set(packages)
    for package in packages:
        for path in (ROOT / package).rglob("*.py"):
            assert not any(name.startswith("tests") for name in imported_names(path)), path
    for path in (ROOT / "scripts").rglob("*.py"):
        assert not any(name.startswith("tests.support") for name in imported_names(path)), path
