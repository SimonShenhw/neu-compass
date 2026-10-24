"""A local API for building and checking the web front end without Google, the models or real data (R2b).

For this machine only: `npm run dev` in web/ talks to it, and the browser acceptance of R2b runs against it. It is
never deployed, production code never imports it, and the API has no test mode; this is the test suite's own
stand-ins put together:

  - a synthetic database in a temporary file: db/init.sql and the three courses of tests/conftest.py;
  - Google replaced: /auth/login-url sends the browser to a sign-in page served here (/__dev/google) whose links
    bring it back to the front end with a code, and /auth/callback exchanges that code with a stand-in; some codes are
    refused the way Google or the claim checks refuse them, one link carries a wrong state, one is "cancel";
  - the models replaced by tests/conftest.py's fixture embedder and reranker;
  - /chat answers from a script, never from Gemini, and HyDE's rescue (which would call it) is off. A question with
    one of these words picks another script: `dev:model-error` (the model fails mid-answer), `dev:no-answer` (it
    gives nothing), `dev:daily-limit` (the day's model calls are used up), `dev:no-done` (the stream ends without
    done), `dev:cut` (the connection drops mid-answer), `dev:stall` (it falls silent for longer than the web front
    end waits).

Every setting starts from the code's default, whatever .env or the environment says, and the session secret is new on
every start, so a restart logs everyone out. The access log is filtered as in production. Both this and the dev server
are on 127.0.0.1: one host name keeps them one site for the browser, so the SameSite=Lax session cookie goes along.

Usage (WSL, from the repository root): python -m tests.support.dev_api [--port 8000]

中文：给新前端开发和验收用的本机 API，不连 Google、不加载模型、不用真实数据（R2b）。只在本机用，不部署，生产代码不
import 它，API 里也没有任何测试模式；这里只是把测试套件自己的替身拼在一起：临时文件里的合成数据库；假的 Google 登录页
（/__dev/google），点链接带着 code 回到前端，回调用替身换 code，有几个 code 会像 Google 或身份检查那样被拒，还有一个
state 不对的链接和一个「取消」；模型换成 tests/conftest.py 的替身；/chat 按脚本回答，从不调用 Gemini，会调用它的 HyDE
补救也关掉。问题里带上面那几个词，就换成对应的脚本：模型中途出错、没有回答、今天的次数用完、流没有 done 就结束、连接中途
断开、停得比前端等的还久。每个设置都从代码里的默认值开始，不管 .env 或环境变量怎么写；每次启动换一个会话密钥，所以重启
就都登出了。访问日志和生产一样过滤。它和开发服务器都在 127.0.0.1，同一个主机名，
浏览器才把它们算作同一个站点，SameSite=Lax 的会话 cookie 才会跟着请求走。
"""

from __future__ import annotations

import argparse
import html
import secrets
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

ROOT = Path(__file__).resolve().parents[2]
HOST = "127.0.0.1"
# The dev server and `npm run preview`. 中文：开发服务器和 `npm run preview`。
FRONT_ENDS = ("http://127.0.0.1:5173", "http://127.0.0.1:4173")
# code -> (what the sign-in page says, the identity Google would vouch for). 中文：code -> （登录页上的字，身份）。
ACCOUNTS = {
    "dev-student": ("Synthetic Student · husky.neu.edu",
                    {"user_id": "dev-sub-student", "email": "synthetic.student@husky.neu.edu",
                     "name": "Synthetic Student"}),
    "dev-second": ("Second Student · northeastern.edu",
                   {"user_id": "dev-sub-second", "email": "synthetic.second@northeastern.edu",
                    "name": "Second Student"}),
    "dev-no-name": ("No display name · husky.neu.edu",
                    {"user_id": "dev-sub-noname", "email": "synthetic.noname@husky.neu.edu", "name": ""}),
}
# code -> (what the sign-in page says, the OAuthError reason). 中文：code -> （登录页上的字，拒绝的原因）。
REFUSALS = {
    "dev-outsider": ("An outside account · example.com (refused: domain)", "domain_not_allowed"),
    "dev-unverified": ("Unverified email (refused)", "email_unverified"),
    "dev-refused": ("Google refuses the code (refused)", "token_exchange_rejected"),
}
WRONG_STATE = "dev-wrong-state-0123456789abcdef"
# The scripted answer, in pieces. 中文：脚本里的回答，分成几块。
ANSWER = ("按合成目录，", "CS 5800 ", "是算法课，", "CS 6140 ", "是机器学习。", "（这是开发用的假回答，", "没有调用模型。）")
PIECE_SECONDS = 0.05  # Between pieces, so the page shows the answer arriving. 中文：块与块之间停一下，页面上看得出在流。
STALL_SECONDS = 35  # Longer than the web front end's 30 s wait. 中文：比前端的 30 秒等得久。
CUT_AFTER_LINES = 3  # dev:cut and dev:no-done stop after meta and two pieces. 中文：meta 和两块以后就停。


def pinned(settings) -> list[str]:
    """The settings configure() sets: every one that has a default, so a test can put them back.
    中文：configure() 设的设置：凡是有默认值的都设，测试好还原。"""
    return [name for name, field in type(settings).model_fields.items() if not field.is_required()]


def configure(settings, db_path: Path) -> None:
    """Point the process's settings at the synthetic world. Every setting first goes back to the code's default,
    whatever .env or the environment says (a request limit or a data path there would change what this API does),
    then the few this API needs are set. Only the Gemini key has no default and stays as it is; nothing here calls
    Gemini.
    中文：把这个进程的设置指向合成的那一套。每个设置先恢复成代码里的默认值，不管 .env 或环境变量怎么写（那里的限流或
    数据路径会改变这个 API 的行为），再设它需要的几项。只有 Gemini key 没有默认值，保持原样；这里不会调用 Gemini。"""
    fields = type(settings).model_fields
    for name in pinned(settings):
        setattr(settings, name, fields[name].get_default(call_default_factory=True))
    settings.sqlite_path = str(db_path)
    settings.web_origins = list(FRONT_ENDS)
    settings.session_secret = secrets.token_urlsafe(32)
    settings.google_oauth_client_id = "dev-client-id"
    settings.google_oauth_client_secret = "dev-client-secret"
    settings.google_oauth_redirect_uri = f"{FRONT_ENDS[0]}/"
    settings.answer_feedback_enabled = False


def make_database(db_path: Path) -> None:
    from db.connection import connect  # noqa: PLC0415
    from tests.conftest import seed_minimal_corpus  # noqa: PLC0415

    conn = connect(db_path)
    try:
        conn.executescript((ROOT / "db" / "init.sql").read_text(encoding="utf-8"))
        seed_minimal_corpus(conn)
        conn.commit()
    finally:
        conn.close()


def exchange(code: str, *, redirect_uri: str | None = None) -> dict:
    """The stand-in for Google's code exchange. 中文：Google 换 code 的替身。"""
    from api.google_oauth import OAuthError  # noqa: PLC0415

    if code in ACCOUNTS:
        return dict(ACCOUNTS[code][1])
    raise OAuthError(reason=REFUSALS[code][1] if code in REFUSALS else "token_exchange_rejected")


def sign_in_page(state: str, redirect_uri: str) -> HTMLResponse:
    """The stand-in for Google's sign-in page: one link per account, plus a wrong state and a cancel. Only the front
    ends' own addresses, the same check as /auth/login-url, so this page sends nobody anywhere else.
    中文：Google 登录页的替身：每个账号一个链接，外加 state 不对和取消。只认前端自己的地址，和 /auth/login-url 一样。"""
    from api.routes.auth import web_redirect_uris  # noqa: PLC0415

    if redirect_uri not in web_redirect_uris():
        return HTMLResponse("Not a web front end address.", status_code=400)

    def link(label: str, **params: str) -> str:
        href = html.escape(f"{redirect_uri}?{urlencode(params)}", quote=True)
        return f'<li><a href="{href}">{html.escape(label)}</a></li>'

    items = [link(label, code=code, state=state) for code, (label, _) in {**ACCOUNTS, **REFUSALS}.items()]
    items.append(link("Synthetic Student, but the state is wrong", code="dev-student", state=WRONG_STATE))
    items.append(link("Cancel (Google sends error=access_denied)", error="access_denied", state=state))
    page = ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"referrer\" content=\"no-referrer\">"
            "<title>Fake Google sign-in</title></head><body><h1>Fake Google sign-in (local development)</h1>"
            "<p>Synthetic accounts only. Nothing here reaches Google.</p><ul>" + "".join(items) + "</ul></body></html>")
    return HTMLResponse(page, headers={"Cache-Control": "no-store"})


def chat_stream(prompt: str) -> Iterator[str]:
    """The stand-in for Gemini's answer stream: the scripted answer, or the failure the question names.
    中文：Gemini 回答流的替身：脚本里的回答，或者问题点名的那种失败。"""
    from llm.gemini_client import GeminiError  # noqa: PLC0415

    if "dev:no-answer" in prompt:
        raise GeminiError("dev: no answer", kind="empty_stream")
    for number, piece in enumerate(ANSWER):
        if number == 2 and "dev:model-error" in prompt:
            raise GeminiError("dev: the model failed", kind="stream_failed")
        time.sleep(STALL_SECONDS if number == 2 and "dev:stall" in prompt else PIECE_SECONDS)
        yield piece


class UsedUp:
    """Today's model calls are used up (batch T). 中文：今天的模型次数已经用完。"""

    def acquire(self) -> bool:
        return False


async def model_budget(request: Request) -> UsedUp | None:
    """No daily limit, unless the question asks for one (FastAPI has read the body already; this reads its copy).
    中文：没有每日上限，除非问题点名要（FastAPI 已经读过请求体，这里读它留下的那份）。"""
    try:
        query = (await request.json()).get("query")
    except (ValueError, AttributeError):
        return None
    return UsedUp() if isinstance(query, str) and "dev:daily-limit" in query else None


class CutChat:
    """`dev:cut` and `dev:no-done`: a /chat answer that stops after meta and two pieces. dev:no-done ends the response
    there, so the stream has no done; dev:cut sends nothing more and never ends it, so uvicorn closes the connection
    the way an API that died mid-answer would.
    中文：dev:cut 和 dev:no-done：/chat 的回答在 meta 和两块以后就停。dev:no-done 在那儿正常结束响应，流里就没有 done；
    dev:cut 什么都不再发、也不结束响应，uvicorn 就像 API 中途死掉那样断开连接。"""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope["path"] != "/chat":
            await self.app(scope, receive, send)
            return
        messages, body = [], b""
        while True:
            message = await receive()
            messages.append(message)
            body += message.get("body", b"")
            if message["type"] != "http.request" or not message.get("more_body"):
                break
        how = "cut" if b"dev:cut" in body else "no-done" if b"dev:no-done" in body else None

        async def replay():
            return messages.pop(0) if messages else await receive()

        lines = 0

        async def stop_early(message) -> None:
            nonlocal lines
            if lines >= CUT_AFTER_LINES:
                return
            if message["type"] == "http.response.body":
                lines += message.get("body", b"").count(b"\n")
                if lines >= CUT_AFTER_LINES and how == "no-done":
                    message = {**message, "more_body": False}
            await send(message)

        await self.app(scope, replay, stop_early if how else send)


def build_dev_app(db_path: Path, *, base: str) -> FastAPI:
    """The real app (create_app) over the synthetic world; `base` is where this API answers, for the sign-in page.
    中文：真正的应用（create_app），跑在合成的那一套上；`base` 是这个 API 的地址，给登录页用。"""
    import api.google_oauth  # noqa: PLC0415
    from api.dependencies import (  # noqa: PLC0415
        get_chat_stream_fn,
        get_hyde_rescue_fn,
        get_model_budget,
        get_oauth_exchange_fn,
    )
    from api.logging import configure_logging  # noqa: PLC0415
    from api.main import create_app  # noqa: PLC0415
    from config import settings  # noqa: PLC0415
    from db.connection import connect  # noqa: PLC0415
    from db.repository import CourseRepository  # noqa: PLC0415
    from rag.hybrid import BM25Corpus  # noqa: PLC0415
    from rag.index import FaissIndex  # noqa: PLC0415
    from tests.conftest import FixtureEmbedder, FixtureReranker  # noqa: PLC0415

    configure(settings, db_path)
    # The API's own logging, which production sets up at startup (skipped here): uvicorn's access log loses the login
    # address's query and names course reads by their template (R2a). 中文：生产在启动时装上的 API 日志（这里不跑启动）：
    # uvicorn 的访问日志去掉登录地址的查询串，课程读取只记路径模板（R2a）。
    configure_logging()
    make_database(db_path)

    def authorize_url(*, state_token: str = "", redirect_uri: str | None = None) -> str:
        query = urlencode({"state": state_token, "redirect_uri": redirect_uri or settings.google_oauth_redirect_uri})
        return f"{base}/__dev/google?{query}"

    # /auth/login-url looks the function up on every call. 中文：/auth/login-url 每次调用时才取这个函数。
    api.google_oauth.authorize_url = authorize_url
    app = create_app(run_startup=False)
    app.dependency_overrides[get_oauth_exchange_fn] = lambda: exchange
    app.add_api_route("/__dev/google", sign_in_page, methods=["GET"], include_in_schema=False)
    # No question reaches a model: the answer is scripted, and HyDE's rescue (Gemini rewriting the question) is off.
    # 中文：没有问题会到模型那里：回答按脚本来，HyDE 的补救（让 Gemini 改写问题）关掉。
    app.dependency_overrides[get_chat_stream_fn] = lambda: chat_stream
    app.dependency_overrides[get_hyde_rescue_fn] = lambda: None
    app.dependency_overrides[get_model_budget] = model_budget
    app.add_middleware(CutChat)

    conn = connect(db_path)
    try:
        embedder = FixtureEmbedder()
        index = FaissIndex()
        indexed = CourseRepository(conn).list_by_status("indexed")
        index.add(embedder.encode([f"raw_{c.course_id}" for c in indexed]), [c.course_id for c in indexed])
        app.state.bm25_corpus = BM25Corpus.from_db(conn)
    finally:
        conn.close()
    app.state.embedder = embedder
    app.state.faiss_index = index
    app.state.reranker = FixtureReranker()
    app.state.ready = True
    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local API for the web front end (synthetic data, fake Google).")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    import uvicorn  # noqa: PLC0415

    with tempfile.TemporaryDirectory(prefix="nc-dev-api-") as directory:
        base = f"http://{HOST}:{args.port}"
        app = build_dev_app(Path(directory) / "dev.sqlite3", base=base)
        print(f"Dev API on {base} for {', '.join(FRONT_ENDS)}. Synthetic data; fake Google at {base}/__dev/google.")
        uvicorn.run(app, host=HOST, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
