"""Keep answers that depend on who is asking out of shared caches (R2a, A25 L3).

A shared cache must not reuse the response to a request that carries `Authorization` (RFC 9111 §3.5), but there is no
such rule for `Cookie`, so a response built from the session cookie has to say so itself. Every route that reads the
caller's identity goes through api.dependencies.get_current_user_id, which marks the request; this middleware then
sends `Cache-Control: private, no-store` with its response, the guest's too, so a cache can neither give one student's
answer to another nor the guest view to someone logged in. Responses that are the same for everyone are not touched.

中文：按身份不同而不同的响应不进共享缓存（R2a，A25 L3）。带 `Authorization` 的请求，共享缓存本来就不能复用它的响应
（RFC 9111 §3.5），`Cookie` 没有这条规则，所以按会话 cookie 生成的响应得自己说明。读调用者身份的路由都经过
api.dependencies.get_current_user_id，它给请求做个记号；这个中间件就给这样的响应加上 `Cache-Control: private,
no-store`，游客的也加：缓存既不能把一个学生的回答给另一个人，也不能把游客版给登录的人。对谁都一样的响应不动。
"""

from __future__ import annotations

from starlette.datastructures import MutableHeaders

# The key get_current_user_id sets in the request's state. 中文：get_current_user_id 在请求的 state 里记的键。
IDENTITY_READ = "identity_read"


class PrivateCacheMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_private(message):
            # The route has run by the time its response starts, so the mark is there or never will be.
            # 中文：响应开始发的时候路由已经跑完了，记号有就是有，没有就不会再有。
            if message["type"] == "http.response.start" and scope.get("state", {}).get(IDENTITY_READ):
                MutableHeaders(scope=message)["cache-control"] = "private, no-store"
            await send(message)

        await self.app(scope, receive, send_private)


__all__ = ["IDENTITY_READ", "PrivateCacheMiddleware"]
