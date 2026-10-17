"""Per-tab caches for read-only page content (OPT-02).

The hero's course count (GET /ready), the Co-op teaser (GET /coop), the program list (GET /programs)
and each curriculum (GET /programs/{id}) are kept in st.session_state, so a rerun does not fetch them
again. Every entry remembers when it was fetched and for which viewer:

- a success is served for SUCCESS_TTL_SECONDS, then fetched again on the next read;
- a failure is remembered for FAILURE_TTL_SECONDS, so the reruns of an outage do not each wait on the
  same request, and the first read after that tries again: a failure is never kept for the life of
  the tab, which is what hid the course count and the Co-op teaser until a reload;
- when a fetch fails for a reason that can pass (transient(): timeout, rate limit, server error,
  transport failure, a response that is not JSON), the last success fetched for the same viewer is
  served until the next try, and the caller gets the ApiError only when there is no such success.
  A definite answer (401, 403, 404, other client errors) drops that success and goes to the caller;
- content that depends on who is asking (the API redacts /coop by the viewer's tier) is stored under
  viewer_scope(), one per session token plus known contribution count (fixed for guests), and an
  entry is never served to another scope, not even as that fallback.

Only GETs go through here. expire_all() (the sidebar's refresh button) makes the next read of every
entry fetch again; it never repeats a chat question, a Co-op submission or a vote. begin_run() and
served_fallback() let the page say when it showed an earlier success because fetching again failed.

中文：页面只读内容的按标签页缓存（OPT-02）。hero 的课程总数（GET /ready）、Co-op 预览（GET /coop）、
项目列表（GET /programs）和每个课程表（GET /programs/{id}）存在 st.session_state 里，rerun 不会重新
获取。每条记录都记着获取时间和是替哪位访客获取的：

- 成功的结果用 SUCCESS_TTL_SECONDS 秒，之后下一次读取时重新获取；
- 失败只记 FAILURE_TTL_SECONDS 秒：故障期间的每次 rerun 不会都卡在同一个请求上，过了这段时间的
  第一次读取会重试。失败绝不会在整个标签页里一直保留——以前课程总数和 Co-op 预览就是这样一直藏到
  重新加载页面；
- 因为可能自己恢复的原因（transient()：超时、限流、服务端错误、连接失败、响应不是 JSON）获取失败
  时，继续给出同一访客上次成功获取的内容，等下一次重试；没有这样的内容时调用方才收到 ApiError。
  明确的答复（401、403、404 等客户端错误）会丢掉上次的成功结果，直接交给调用方；
- 随访客变化的内容（API 按访客等级裁剪 /coop）存在 viewer_scope() 下，每个会话 token 加已知贡献数
  一个范围，游客固定。记录绝不会给另一个范围用，失败时的回退也不行。

这里只走 GET。expire_all()（侧边栏的刷新按钮）让每条记录下一次读取时重新获取；它绝不会重发提问、
Co-op 投稿或评价。begin_run() 和 served_fallback() 让页面在因为重新获取失败而显示了上次的成功结果
时说明一句。
"""

from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass, replace
from typing import Any, Callable, MutableMapping

from app.api_client import ApiError

SUCCESS_TTL_SECONDS = 300.0
FAILURE_TTL_SECONDS = 30.0

READY_KEY = "_ready_info"
COOP_TEASER_KEY = "_coop_teaser_cache"
PROGRAMS_KEY = "_programs_cache"
CURRICULUM_KEY = "_curriculum_cache"  # A dict of program_id -> entry. 中文：program_id -> 记录的字典。

PUBLIC_SCOPE = "public"
GUEST_SCOPE = "guest"

# How many reads of the current script run served an earlier success because fetching again failed.
# 中文：本次脚本运行里，有几次读取因为重新获取失败而给出了上次的成功结果。
FALLBACKS_KEY = "_view_cache_fallbacks"
# A 2xx whose body is not JSON (a proxy or maintenance page) is reported like a bad gateway.
# 中文：2xx 但内容不是 JSON（代理或维护页面）时，按网关错误报告。
INVALID_RESPONSE_DETAIL = "服务返回了无法识别的内容，请稍后手动重试。"
# The sidebar button that calls expire_all(); the landing's notice names it with the same text.
# 中文：调用 expire_all() 的侧边栏按钮；落地页的说明用同一段文字提到它。
REFRESH_LABEL = "🔄 刷新页面内容"

# Tests replace this; monotonic, so a wall-clock change never expires or revives an entry.
# 中文：测试会替换它；用单调时钟，改系统时间不会让记录提前过期或复活。
clock: Callable[[], float] = time.monotonic


@dataclass(frozen=True)
class _Entry:
    fetched_at: float
    ok: bool                 # Whether the last fetch succeeded. 中文：最近一次获取是否成功。
    has_value: bool          # Whether a success was ever stored for this scope. 中文：这个范围是否有过成功结果。
    value: Any               # The last success (served while a later failure is fresh). 中文：上次成功的结果。
    error: tuple | None      # (status_code, detail, error_type) of the last failure. 中文：最近一次失败。
    scope: str


_NO_VALUE = object()


def viewer_scope(state: MutableMapping[str, Any]) -> str:
    """Content the API redacts by viewer: one scope per token and contribution count; fixed for guests.

    Missing counts mean zero; malformed counts use c? and cannot reuse a real count's entry. Store a
    digest, not another copy of the token; do not duplicate the API's tier rules here.
    中文：每个会话 token 加贡献数一个范围，游客固定 guest。缺失计数按 0，畸形值为 c?，不与真实计数
    共用。只存 token 摘要，不多存原文；不在客户端复制 API 等级规则。"""
    token = state.get("session_token")
    if not isinstance(token, str) or not token:
        return GUEST_SCOPE
    count = state.get("user_contribution_count", 0)
    contribution = str(count) if type(count) is int and count >= 0 else "?"
    return "session:" + hashlib.sha256(token.encode("utf-8")).hexdigest() + ":c" + contribution


def curricula(state: MutableMapping[str, Any]) -> dict:
    """The per-program container, replacing a missing or malformed one with an empty dict.
    中文：按项目存放的容器；没有或格式不对时换成空字典。"""
    container = state.get(CURRICULUM_KEY)
    if not isinstance(container, dict):
        container = {}
        state[CURRICULUM_KEY] = container
    return container


def transient(exc: ApiError) -> bool:
    """A failure that can pass on its own: a timeout, a rate limit or a server error. ApiClient reports
    transport failures as 503/504 and cached() a response that is not JSON as 502, so those count too.
    401, 403, 404 and other client errors are answers, not outages.
    中文：可能自己恢复的失败：超时、限流、服务端错误。ApiClient 把连接失败报成 503/504，cached() 把
    不是 JSON 的响应报成 502，所以也算。401、403、404 等客户端错误是明确的答复，不是故障。"""
    return exc.status_code in {408, 429} or exc.status_code >= 500


def begin_run(state: MutableMapping[str, Any]) -> None:
    """Call at the start of a script run, before any cached read; see served_fallback().
    中文：在脚本每次运行开始、任何缓存读取之前调用；见 served_fallback()。"""
    state[FALLBACKS_KEY] = 0


def served_fallback(state: MutableMapping[str, Any]) -> bool:
    """Whether a read since begin_run() served an earlier success because fetching again failed.
    中文：自 begin_run() 以来，是否有读取因为重新获取失败而给出了上次的成功结果。"""
    count = state.get(FALLBACKS_KEY)
    return isinstance(count, int) and count > 0


def _note_fallback(state: MutableMapping[str, Any]) -> None:
    count = state.get(FALLBACKS_KEY)
    state[FALLBACKS_KEY] = (count if isinstance(count, int) else 0) + 1


def _fresh(entry: _Entry, now: float) -> bool:
    ttl = SUCCESS_TTL_SECONDS if entry.ok else FAILURE_TTL_SECONDS
    return 0 <= now - entry.fetched_at < ttl


def _serve(entry: _Entry) -> Any:
    if entry.ok or entry.has_value:
        return entry.value
    status_code, detail, error_type = entry.error
    # Rebuilt, not the stored exception: keeping that object would keep its traceback (and the
    # frames' locals) alive. The Retry-After seconds are left out because the countdown is no longer
    # current. 中文：重新构造，而不是存下原来的异常对象：留着它会让它的 traceback（以及各帧的局部
    # 变量）一直留在内存里。Retry-After 的秒数不再带上，因为那个倒计时已经过时。
    raise ApiError(status_code, detail, error_type=error_type)


def cached(
    container: MutableMapping[str, Any],
    key: str,
    fetch: Callable[[], Any],
    *,
    scope: str = PUBLIC_SCOPE,
    on_success: Callable[[Any, Any], None] | None = None,
    state: MutableMapping[str, Any] | None = None,
) -> Any:
    """container[key] while fresh for this scope; otherwise call fetch() once and remember the outcome.

    A failed fetch raises its own ApiError unless it is transient() and this scope has an earlier
    success, which is then served instead; the reads while that failure is fresh raise a rebuilt
    ApiError (same status code, text and error type, without the Retry-After seconds) or serve that
    success. A ValueError from fetch() (a 2xx body that is not JSON) counts as a 502 ApiError; other
    errors are not cached and propagate. Each read that serves an earlier success because of a
    failure is counted in `state` (default: the container) for served_fallback().
    on_success(previous, value) runs after a fetch succeeds; previous is the last success for this
    scope, or None when there was none.

    中文：对这个范围仍有效时返回 container[key]；否则调用一次 fetch() 并记下结果。获取失败时抛出它
    自己的 ApiError，除非失败属于 transient()、并且这个范围有过成功结果，这时改为给出那个结果；失败
    仍有效期间的读取，要么抛出重新构造的 ApiError（状态码、提示文字和错误类型相同，不带 Retry-After
    秒数），要么给出那个成功结果。fetch() 抛出的 ValueError（2xx 但内容不是 JSON）按 502 的 ApiError
    处理；其他错误不缓存、照常抛出。每次因为失败而给出上次成功结果的读取，都记在 `state`（默认是
    container）里，供 served_fallback() 使用。获取成功后调用 on_success(previous, value)：previous 是
    这个范围上次的成功结果，没有时为 None。"""
    now = clock()
    entry = container.get(key)
    if not isinstance(entry, _Entry) or entry.scope != scope:
        entry = None
    if entry is not None and _fresh(entry, now):
        if not entry.ok and entry.has_value:
            _note_fallback(container if state is None else state)
        return _serve(entry)
    previous = entry.value if entry is not None and entry.has_value else _NO_VALUE
    try:
        value = fetch()
    except (ApiError, ValueError) as raised:
        exc = raised if isinstance(raised, ApiError) else ApiError(
            502, INVALID_RESPONSE_DETAIL, error_type="invalid_response")
        keep = previous is not _NO_VALUE and transient(exc)
        container[key] = _Entry(
            fetched_at=now, ok=False, has_value=keep, value=previous if keep else None,
            error=(exc.status_code, exc.detail, exc.error_type), scope=scope,
        )
        if not keep:
            if exc is raised:
                raise
            raise exc from None
        _note_fallback(container if state is None else state)
        return previous
    container[key] = _Entry(fetched_at=now, ok=True, has_value=True, value=value, error=None, scope=scope)
    if on_success is not None:
        on_success(None if previous is _NO_VALUE else previous, value)
    return value


def store(container: MutableMapping[str, Any], key: str, value: Any, *, scope: str = PUBLIC_SCOPE) -> None:
    """Record a success fetched elsewhere (the plan link's own GET) as fresh.
    中文：把别处获取的成功结果（方案链接自己的 GET）记成新获取的。"""
    container[key] = _Entry(fetched_at=clock(), ok=True, has_value=True, value=value, error=None, scope=scope)


def peek(container: MutableMapping[str, Any], key: str, *, scope: str = PUBLIC_SCOPE) -> Any:
    """The last success stored for this scope, fresh or not, without fetching; None when there is none.
    中文：这个范围存过的上次成功结果（不管是否过期），不获取；没有时为 None。"""
    entry = container.get(key)
    if isinstance(entry, _Entry) and entry.scope == scope and entry.has_value:
        return entry.value
    return None


def expire_all(state: MutableMapping[str, Any]) -> None:
    """Make the next read of every entry fetch again (the refresh button). The last successes stay as
    the fallback and for comparing a curriculum's plans; nothing outside these caches is touched.
    中文：让每条记录下一次读取时重新获取（刷新按钮）。上次的成功结果留着，作失败时的回退，也用来比较
    课程表里的方案；这些缓存以外的东西一概不动。"""
    for key in (READY_KEY, COOP_TEASER_KEY, PROGRAMS_KEY):
        _expire(state, key)
    nested = state.get(CURRICULUM_KEY)
    if isinstance(nested, dict):
        for key in list(nested):
            _expire(nested, key)


def _expire(container: MutableMapping[str, Any], key: str) -> None:
    entry = container.get(key)
    if isinstance(entry, _Entry):
        container[key] = replace(entry, fetched_at=-math.inf)


__all__ = [
    "COOP_TEASER_KEY",
    "CURRICULUM_KEY",
    "FAILURE_TTL_SECONDS",
    "FALLBACKS_KEY",
    "GUEST_SCOPE",
    "INVALID_RESPONSE_DETAIL",
    "PROGRAMS_KEY",
    "PUBLIC_SCOPE",
    "READY_KEY",
    "REFRESH_LABEL",
    "SUCCESS_TTL_SECONDS",
    "begin_run",
    "cached",
    "curricula",
    "expire_all",
    "peek",
    "served_fallback",
    "store",
    "transient",
    "viewer_scope",
]
