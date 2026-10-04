"""Thin httpx wrapper around the FastAPI backend.

对 FastAPI 后端的一层薄 httpx 封装。

Streamlit pages use this instead of constructing requests inline so:
- tests can mock transport via httpx.MockTransport (no live server needed)
- timeouts / auth headers / base URL live in one place
- the public surface mirrors the backend route set, one method per route

Streamlit 页面用它而不是内联构造请求，原因是：
- 测试可以用 httpx.MockTransport 模拟传输层（不需要起一个真实服务）
- 超时 / 认证头 / base URL 都集中在一个地方
- 公开接口与后端路由集合一一对应，每个路由一个方法

Usage from a Streamlit page:
    from app.api_client import ApiClient
    with ApiClient(user_id=state["user_id"]) as api:
        body = api.search(query, k=10)
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

import httpx

from config import settings


def _retry_seconds(value):
    """Bounded delta-seconds hint only; dates/invalid headers remain unknown.
    中文：提示而非倒计时或重试指令；不自动 sleep、补发或接受任意数值。
    """
    if isinstance(value, str) and re.fullmatch(r'[0-9]{1,4}', value.strip()):
        seconds = int(value.strip())
        return seconds if seconds <= 3600 else None
    return None


class ApiError(RuntimeError):
    """Non-2xx response from the API. .status_code + .detail are exposed
    for the UI to render a useful message.

    API 返回的非 2xx 响应。暴露 .status_code + .detail，供 UI 渲染出
    有意义的提示信息。"""

    def __init__(self, status_code: int, detail: str, *, error_type: str | None = None,
                 retry_after_seconds: int | None = None) -> None:
        self.status_code = status_code
        self.error_type = (error_type if isinstance(error_type, str)
                           and re.fullmatch(r'[a-z_]{1,64}', error_type) else None)
        self.retry_after_seconds = (retry_after_seconds if type(retry_after_seconds) is int
                                    and 0 <= retry_after_seconds <= 3600 else None)
        later = (f'{self.retry_after_seconds} 秒后' if self.retry_after_seconds else '稍后')
        # Transient failures never reflect proxy HTML / exception / request data.
        # 中文：状态明确的暂时故障不展示服务端原文，不自动重发写请求。
        if status_code == 429:
            detail = f'请求过于频繁，请{later}手动重试。'
        elif status_code == 503:
            detail = f'服务正忙，请{later}手动重试。' if self.error_type == 'service_busy' else f'服务暂不可用，请{later}手动重试。'
        elif status_code in {408, 504}:
            detail = '请求超时，处理可能仍在进行；请稍后手动重试，避免重复提交。'
        self.detail = detail
        super().__init__(f"API {status_code}: {detail}")


class ApiClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        session_token: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        # 30s default: the NAS OpenVINO path runs /search at p50 ~2.3s but the
        # ONNX-CPU fallback is 7-10s — the old 10s default turned a degraded
        # backend into raw ReadTimeout tracebacks in the Streamlit UI.
        # 中文:默认 30 秒：NAS OpenVINO 路径下 /search 的 p50 约 2.3 秒，
        # 但 ONNX-CPU 兜底路径要 7-10 秒 —— 旧的 10 秒默认值会让降级中
        # 的后端在 Streamlit UI 里直接抛出原始的 ReadTimeout 堆栈跟踪。
        self.base_url = (base_url or settings.api_base_url).rstrip("/")
        headers: dict[str, str] = {}
        if session_token:
            headers["Authorization"] = f"Bearer {session_token}"
        self._client = httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
        )

    # === Context manager so callers can `with ApiClient() as api:` ===
    # 中文:上下文管理器，让调用方可以 `with ApiClient() as api:`

    def __enter__(self) -> "ApiClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    # === Auth (ADR-0021: signed session token from POST /auth/callback) ===
    # 中文(ADR-0021):来自 POST /auth/callback 的签名会话 token

    def set_session_token(self, token: str | None) -> None:
        if token:
            self._client.headers["Authorization"] = f"Bearer {token}"
        else:
            self._client.headers.pop("Authorization", None)

    # === Routes ===
    # 中文:路由

    def health(self) -> dict[str, Any]:
        return self._get("/health")

    def ready(self) -> dict[str, Any]:
        return self._get("/ready")

    def search(
        self,
        query: str,
        *,
        k: int = 10,
        term: str | None = None,
        credits: int | None = None,
        delivery_mode: str | None = None,
        professor: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"query": query, "k": k}
        if term:
            body["term"] = term
        if credits is not None:
            body["credits"] = credits
        if delivery_mode:
            body["delivery_mode"] = delivery_mode
        if professor:
            body["professor"] = professor
        return self._post("/search", body)

    def get_course(self, course_id: str) -> dict[str, Any]:
        return self._get(f"/course/{course_id}")

    def resolve_course(self, ref: str) -> dict[str, Any]:
        """Deep-link `?course=` ref → `{"ref", "matches": [...]}`.

        Never raises for "no such course" — an unresolvable ref comes back
        as an empty `matches` list, so ApiError here still means the API
        itself is unhappy.

        深链 `?course=` 的引用 → `{"ref", "matches": [...]}`。

        「查无此课」不会抛异常 —— 解析不出来时 `matches` 为空列表，因此
        这里抛出的 ApiError 依然只代表 API 本身出了问题。"""
        return self._get("/resolve/course", params={"ref": ref})

    def list_programs(self) -> list[dict[str, Any]]:
        return self._get("/programs")

    def get_program_policies(self, program_id: str, plan_id: str) -> dict[str, Any]:
        """Fetch the explicitly selected plan only; callers must not cache evidence."""
        return self._get(f"/programs/{quote(program_id, safe='')}/plans/{quote(plan_id, safe='')}/policies")

    def get_program_curriculum(self, program_id: str) -> dict[str, Any]:
        return self._get(f"/programs/{program_id}")

    def list_coop(self) -> list[dict[str, Any]]:
        return self._get("/coop")

    def upload_coop(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/coop", payload)

    def submit_answer_feedback(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post('/feedback', payload)

    def auth_me(self) -> dict[str, Any]:
        """Identity behind the current session token (GET /auth/me).
        Raises ApiError 401 when the token is missing/invalid/expired.

        当前会话 token 背后的身份（GET /auth/me）。token 缺失/无效/
        过期时抛出 ApiError 401。"""
        return self._get("/auth/me")

    # === OAuth callback ===
    # 中文:OAuth 回调

    def oauth_callback(
        self,
        code: str,
        *,
        redirect_uri: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"code": code}
        if redirect_uri:
            body["redirect_uri"] = redirect_uri
        return self._post("/auth/callback", body)

    # === Chat (streaming) ===
    # 中文:聊天（流式）

    def chat_stream(
        self,
        body: dict[str, Any],
    ) -> Iterator[dict[str, Any]]:
        """Iterate over /chat NDJSON events.

        Each yield is a parsed dict with shape
        {"type": "meta"|"token"|"error"|"done", ...}. Caller renders
        accordingly (Streamlit st.write_stream consumes the `text` from
        token events; meta is stashed for evidence bubbles).

        Raises ApiError if the server returns non-200 BEFORE streaming
        starts. Errors mid-stream surface as in-stream `error` events,
        not exceptions — so the caller still gets the partial output.

        遍历 /chat 的 NDJSON 事件流。

        每次产出都是一个解析好的字典，形状为
        {"type": "meta"|"token"|"error"|"done", ...}。调用方据此渲染
        （Streamlit 的 st.write_stream 消费 token 事件里的 `text`；
        meta 被暂存起来用于证据气泡）。

        若服务端在开始流式输出之前就返回了非 200，抛出 ApiError。
        流式过程中途的错误表现为流内的 `error` 事件，而不是异常 ——
        这样调用方依然能拿到已产出的部分内容。
        """
        completed = False
        try:
            with self._client.stream("POST", "/chat", json=body) as resp:
                if resp.status_code >= 400:
                    resp.read()
                    self._unwrap(resp)  # raises ApiError
                for raw_line in resp.iter_lines():
                    line = (
                        raw_line.strip() if isinstance(raw_line, str) else raw_line
                    )
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        # Malformed line — skip rather than break the stream.
                        # 中文:格式错误的行 —— 跳过而不是打断整个流。
                        continue
                    if not isinstance(event, dict):
                        continue
                    yield event
                    if event.get('type') in ('done', 'error'):
                        completed = True
                        return
        except httpx.HTTPError as e:
            # Mid-stream transport failure (read timeout between chunks,
            # API container restart). Degrade to an in-stream error event —
            # same shape as server-side failures — so the page keeps the
            # partial output instead of crashing on a raw httpx exception.
            # 中文:流式传输中途失败（分块之间读超时、API 容器重启）。
            # 降级为一个流内 error 事件 —— 与服务端失败的形状一致 ——
            # 这样页面能保留已产出的部分内容，而不是被一个原始的 httpx
            # 异常直接搞崩溃。
            yield {
                "type": "error",
                "detail": "Connection to API lost. 仅保留部分回答，未完整结束；请稍后手动重试。",
                "error_type": 'transport_timeout' if isinstance(e, httpx.TimeoutException) else 'transport_error',
            }
            return
        if not completed:
            yield {'type': 'error', 'error_type': 'incomplete_stream',
                   'detail': '回答流未完整结束；仅保留部分内容，请稍后手动重试。'}

    # === Internal ===
    # 中文:内部实现

    def _get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        try:
            return self._unwrap(self._client.get(path, params=params))
        except httpx.TimeoutException:
            raise ApiError(504, 'timeout', error_type='transport_timeout') from None
        except httpx.HTTPError:
            # ConnectError (API container down/restarting), ReadError /
            # RemoteProtocolError (died mid-response), ... — without this
            # wrap they propagate raw and crash the whole Streamlit page,
            # since every UI call site catches ApiError only.
            # 中文:ConnectError（API 容器挂了/正在重启）、ReadError /
            # RemoteProtocolError（响应途中断掉）等等 —— 没有这层包装，
            # 它们会原样传播，把整个 Streamlit 页面搞崩溃，因为每个 UI
            # 调用点都只捕获 ApiError。
            raise ApiError(503, 'unreachable', error_type='transport_error') from None

    def _post(self, path: str, body: dict[str, Any]) -> Any:
        try:
            return self._unwrap(self._client.post(path, json=body))
        except httpx.TimeoutException:
            raise ApiError(504, 'timeout', error_type='transport_timeout') from None
        except httpx.HTTPError:
            raise ApiError(503, 'unreachable', error_type='transport_error') from None

    @staticmethod
    def _unwrap(r: httpx.Response) -> Any:
        if r.status_code >= 400:
            error_type = None
            try:
                body = r.json()
                detail = body.get('detail', r.text)
                error_type = body.get('error_type')
            except Exception:
                detail = r.text
            raise ApiError(r.status_code, str(detail), error_type=error_type,
                           retry_after_seconds=_retry_seconds(r.headers.get('retry-after')))
        if r.status_code == 204:
            return None
        return r.json()


__all__ = ["ApiClient", "ApiError"]
