"""What the Streamlit page sent with each /chat question, and the line it showed for a failed one, kept for the offline
route evaluation when R8 deleted app/. The same code as app/chat_view.py, app/state_manager.py and app/api_client.py
had, so the reports stay comparable.

The web front end keeps the same history window (six messages, then the empty ones dropped, 4000 characters each:
web/src/models/conversation.ts) but builds a failed request's message its own way.
中文：Streamlit 页每次提问带的历史和上下文课程、请求失败时显示的那句话。R8 删 app/ 时搬到这里给离线路由评测用，代码和原来
一样，报告前后可比。新前端的历史窗口相同（取最近六条、去掉空的、每条 4000 字），失败请求的那条消息写法不同。
"""

from __future__ import annotations

import re

SEARCH_K = 10  # The page asked for ten courses (app/state_manager.py's DEFAULTS); the web asks for ten too.


def recent_history(messages: list[dict], limit: int = 6) -> list[dict]:
    """The last `limit` messages as ChatRequest.history: slice, then drop the empty ones, then cut each to 4000
    characters (the API's ChatTurn bound). 中文：先取最后几条，再去掉空的，每条截到 4000 字符（API 的上限）。"""
    return [
        {"role": m["role"], "content": str(m["content"])[:4000]}
        for m in messages[-limit:]
        if m.get("content")
    ]


def context_course_ids(messages: list[dict], limit: int = 10) -> list[str]:
    """The courses of the latest assistant message with evidence, in order and with duplicates, at most `limit`.
    中文：最近一条带证据的助手消息里的课程，不去重、不改顺序，最多 `limit` 门。"""
    for m in reversed(messages):
        if m.get("role") == "assistant" and m.get("evidence"):
            return [ev["course_id"] for ev in m["evidence"]][:limit]
    return []


def _retry_seconds(value: object) -> int | None:
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,4}", value.strip()):
        seconds = int(value.strip())
        return seconds if seconds <= 3600 else None
    return None


def _line(status: int, detail: str, error_type: object, retry_after: int | None) -> str:
    error_type = error_type if isinstance(error_type, str) and re.fullmatch(r"[a-z_]{1,64}", error_type) else None
    later = f"{retry_after} 秒后" if retry_after else "稍后"
    # A transient failure never shows the server's own words. 中文：暂时故障不显示服务端原文。
    if status == 429:
        return f"请求过于频繁，请{later}手动重试。"
    if status == 503:
        return f"服务正忙，请{later}手动重试。" if error_type == "service_busy" else f"服务暂不可用，请{later}手动重试。"
    if status in {408, 504}:
        return "请求超时，处理可能仍在进行；请稍后手动重试，避免重复提交。"
    if status == 502 and error_type == "invalid_response":
        return "服务返回了无法识别的内容，请稍后手动重试。"
    if status >= 500:
        return "服务暂时出错，请稍后手动重试。"
    return detail


def failure_detail(response) -> str | None:
    """The line the page showed for a request answered with `response`, or None when the page read it as a success
    (a 2xx or 3xx with JSON, or a 204). 中文：页面对这个响应显示的那句话；页面当成功读的（带 JSON 的 2xx、3xx，或 204）
    返回 None。"""
    if response.status_code < 400:
        if response.status_code == 204:
            return None
        try:
            response.json()
        except ValueError:
            return _line(502, "invalid_response", "invalid_response", None)
        return None
    try:
        body = response.json()
    except ValueError:
        body = None
    detail, error_type = "请求未完成，请稍后手动重试。", None
    if isinstance(body, dict):
        if isinstance(body.get("detail"), str):
            detail = body["detail"]
        error_type = body.get("error_type")
    return _line(response.status_code, detail, error_type, _retry_seconds(response.headers.get("retry-after")))
