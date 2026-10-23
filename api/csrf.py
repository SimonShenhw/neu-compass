"""Refuse cross-site writes that ride on the API's session cookie (R2a).

The browser sends the session cookie by itself, so a write that carries it must show where it comes from: an `Origin`
in WEB_ORIGINS and the header `X-NEU-Compass: 1`. A page on another origin cannot send that header without a CORS
preflight, which the CORS middleware only answers for WEB_ORIGINS. Only writes (not GET, HEAD or OPTIONS) that carry
the cookie and no `Authorization` header are checked: a Bearer token is never sent by the browser on its own, and a
request without the cookie has no session to abuse. A refusal is a fixed 403 that echoes nothing.

Which credential a request carries is read exactly as api.dependencies.get_current_user_id reads it, through
Starlette's own request headers and cookies, so the two can never disagree: an empty `Authorization` header does not
exempt a request whose cookie is then used, and a cookie Starlette finds is never missed here.

The cookie mode of `/auth/callback` makes the same check itself (`from_web_origin`), with or without a cookie: a page
elsewhere must not log the browser into an account of its choosing (login CSRF).

中文：拒绝借着 API 会话 cookie 的跨站写请求（R2a）。cookie 是浏览器自己带的，所以带着它的写请求要说明从哪儿来：
`Origin` 在 WEB_ORIGINS 里，而且带 `X-NEU-Compass: 1`。别的来源的网页要发这个头，得先过 CORS 预检，而 CORS 只给
WEB_ORIGINS 放行。只查带 cookie、不带 `Authorization` 的写请求（GET、HEAD、OPTIONS 以外）：Bearer 令牌浏览器从来不会
自己带，不带 cookie 的请求也没有会话可冒用。拒绝时固定回 403，什么也不回显。
请求带的是哪种凭证，和 api.dependencies.get_current_user_id 用同一套 Starlette 的请求头和 cookie 来读，两边不会不一致：
空的 `Authorization` 头不能让一个随后要用 cookie 的请求免查，Starlette 认得出的 cookie 这里也不会漏掉。
`/auth/callback` 的 cookie 模式自己也做同样的检查（`from_web_origin`），不管带没带 cookie：别的网站不能把浏览器登录成
它选的账号（登录劫持）。
"""

from __future__ import annotations

import json

from starlette.requests import HTTPConnection
from starlette.responses import Response

from api.session_cookie import COOKIE_NAME

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
MARKER_HEADER = "X-NEU-Compass"
_BODY = json.dumps({"detail": "Cross-site request refused.", "error_type": "csrf_rejected",
                    "status_code": 403}).encode("utf-8")


def from_web_origin(request: HTTPConnection, origins) -> bool:
    """One `Origin`, among `origins`, and one `X-NEU-Compass: 1`: a request the web front end sent.
    中文：正好一个 `Origin`，在 `origins` 里，并且正好一个 `X-NEU-Compass: 1`：新前端发的请求。"""
    found = request.headers.getlist("origin")
    return len(found) == 1 and found[0] in origins and request.headers.getlist(MARKER_HEADER) == ["1"]


def refusal() -> Response:
    """The fixed 403 for a cross-site request, the same bytes wherever it is sent. It echoes nothing.
    中文：跨站请求固定的 403，在哪里发出都是同样的字节，什么也不回显。"""
    return Response(_BODY, status_code=403, media_type="application/json", headers={"cache-control": "no-store"})


class CsrfMiddleware:
    def __init__(self, app, *, origins):
        self.app, self.origins = app, frozenset(origins)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") in SAFE_METHODS:
            return await self.app(scope, receive, send)
        request = HTTPConnection(scope)
        if request.headers.get("Authorization", "") or not request.cookies.get(COOKIE_NAME, ""):
            return await self.app(scope, receive, send)
        if from_web_origin(request, self.origins):
            return await self.app(scope, receive, send)
        await refusal()(scope, receive, send)


__all__ = ["CsrfMiddleware", "MARKER_HEADER", "SAFE_METHODS", "from_web_origin", "refusal"]
