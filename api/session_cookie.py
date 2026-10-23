"""The API's session cookie for the new web front end (R2a).

The same signed token as `Authorization: Bearer` (api.session_tokens), carried in an HttpOnly cookie on the API's own
host, so front-end script can never read it. `__Host-` makes the browser insist on Secure, Path=/ and no Domain, so no
sibling subdomain can plant a cookie of this name (session fixation). SameSite=Lax still sends it on requests from the
front end, because compass and api are the same site. Writes that carry it are checked by api/csrf.py.

中文：API 给新前端用的会话 cookie（R2a）。里面是和 `Authorization: Bearer` 同一种签名令牌（api.session_tokens），放在
API 自己主机上的 HttpOnly cookie 里，前端脚本永远读不到。`__Host-` 前缀让浏览器强制 Secure、Path=/、不带 Domain，
别的子域名设不了同名 cookie（防会话固定）。compass 和 api 是同一个站点，所以 SameSite=Lax 照样会在前端的请求里带上。
带着它的写请求由 api/csrf.py 检查。
"""

from __future__ import annotations

from starlette.responses import Response

from config import settings

COOKIE_NAME = "__Host-nc_api_session"
_ATTRIBUTES = {"path": "/", "secure": True, "httponly": True, "samesite": "lax"}


def set_session_cookie(response: Response, token: str) -> None:
    """Attach the session cookie; it lasts as long as the token itself. 中文：设会话 cookie，和令牌一样长。"""
    response.set_cookie(COOKIE_NAME, token, max_age=settings.session_max_age_seconds, **_ATTRIBUTES)


def expire_session_cookie(response: Response) -> None:
    """Make the browser drop the session cookie now. 中文：让浏览器马上丢掉会话 cookie。"""
    response.delete_cookie(COOKIE_NAME, **_ATTRIBUTES)


def expired_session_cookie_header() -> str:
    """The Set-Cookie value of expire_session_cookie(), for an HTTPException's headers.
    中文：expire_session_cookie() 的 Set-Cookie 值，给 HTTPException 的 headers 用。"""
    response = Response()
    expire_session_cookie(response)
    return response.headers["set-cookie"]


__all__ = ["COOKIE_NAME", "expire_session_cookie", "expired_session_cookie_header", "set_session_cookie"]
