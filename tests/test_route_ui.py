"""eval/route_ui.py (R8): what the Streamlit page sent with a question and showed for a failed one, kept for the offline
route evaluation. The history and context tests are app/'s (test_page_orchestration.py) pointed at the copy; the
failure lines are app/api_client.py's ApiError text, which the copy matched on every status from 100 to 599 before R8
deleted app/. Synthetic messages and responses only.
中文：搬到 eval/route_ui.py 的代码。历史和上下文的测试来自 app/ 的测试，改指这里；失败那句是 app/api_client.py 的
ApiError 文字，R8 删 app/ 之前在 100 到 599 的每个状态码上核对过一致。只用合成数据。
"""

import copy

import httpx
import pytest

from eval.route_ui import SEARCH_K, context_course_ids, failure_detail, recent_history

COURSES = [{"course_id": "c-synthetic-1"}, {"course_id": "c-synthetic-2"}]
GENERIC = "请求未完成，请稍后手动重试。"


@pytest.mark.parametrize("limit", [6, 2, 0, -2])
def test_history_window_and_slice_before_filtering(limit):
    messages = [{"role": "user" if i % 2 == 0 else "assistant", "content": str(i), "extra": i} for i in range(9)]
    messages[-2]["content"] = ""
    messages[-1]["content"] = None
    original = copy.deepcopy(messages)
    expected_indices = {6: [3, 4, 5, 6], 2: [], 0: list(range(7)), -2: list(range(2, 7))}[limit]
    assert recent_history(messages, limit) == [{"role": messages[i]["role"], "content": str(i)} for i in expected_indices]
    assert messages == original


def test_history_conversion_and_4000_character_bound_are_exact():
    assert recent_history([
        {"role": "assistant", "content": "界" * 4001, "evidence": COURSES},
        {"role": "user", "content": 123}, {"role": "user", "content": 0},
        {"role": "user", "content": " \t "},
    ]) == [{"role": "assistant", "content": "界" * 4000},
        {"role": "user", "content": "123"}, {"role": "user", "content": " \t "}]
    assert recent_history([]) == []
    with pytest.raises(KeyError):
        recent_history([{"content": "truthy"}])


@pytest.mark.parametrize("limit,expected", [(10, ["a", "b", "a"]), (1, ["a"]), (0, []), (-1, ["a", "b"])])
def test_context_latest_assistant_evidence_keeps_order_and_duplicates(limit, expected):
    messages = [
        {"role": "assistant", "evidence": [{"course_id": "old"}]},
        {"role": "assistant", "evidence": [{"course_id": "a"}, {"course_id": "b"}, {"course_id": "a"}]},
        {"role": "assistant", "evidence": []}, {"role": "user", "evidence": [{"course_id": "not-user"}]},
    ]
    original = copy.deepcopy(messages)
    assert context_course_ids(messages, limit) == expected
    assert messages == original


def test_context_default_cap_and_existing_malformed_behavior():
    assert context_course_ids([{"role": "assistant", "evidence": [{"course_id": str(i)} for i in range(12)]}]) == [str(i) for i in range(10)]
    assert context_course_ids([]) == []
    assert context_course_ids([{"role": "user", "evidence": COURSES}]) == []
    with pytest.raises(KeyError):
        context_course_ids([{"role": "assistant", "evidence": [{}]}])


def test_the_default_window_is_six_messages():
    messages = [{"role": "user" if i % 2 == 0 else "assistant", "content": str(i)} for i in range(8)]
    assert [m["content"] for m in recent_history(messages)] == [str(i) for i in range(2, 8)]


def test_the_eval_asks_for_ten_courses_as_the_pages_do():
    assert SEARCH_K == 10


@pytest.mark.parametrize("status,body,headers,line", [
    (400, {"detail": "the API's own words"}, {}, "the API's own words"),
    (409, {"detail": "冲突的原话", "reason": "program_conflict"}, {}, "冲突的原话"),
    (422, {"detail": [{"loc": ["body", "query"]}]}, {}, GENERIC),  # A detail that is not text. 中文：detail 不是文字。
    (400, ["a list"], {}, GENERIC),
    (404, None, {}, GENERIC),  # Not JSON. 中文：不是 JSON。
    (429, {"detail": "private-overload-canary"}, {"Retry-After": "7"}, "请求过于频繁，请7 秒后手动重试。"),
    (429, {}, {"Retry-After": " 7 "}, "请求过于频繁，请7 秒后手动重试。"),
    (429, {}, {"Retry-After": "3600"}, "请求过于频繁，请3600 秒后手动重试。"),
    (429, {}, {"Retry-After": "3601"}, "请求过于频繁，请稍后手动重试。"),
    (429, {}, {"Retry-After": "0"}, "请求过于频繁，请稍后手动重试。"),
    (429, {}, {"Retry-After": "7.5"}, "请求过于频繁，请稍后手动重试。"),
    (429, {}, {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}, "请求过于频繁，请稍后手动重试。"),
    (503, {"detail": "synthetic server detail", "error_type": "service_busy"}, {"Retry-After": "7"},
     "服务正忙，请7 秒后手动重试。"),
    (503, {"error_type": "Service-Busy"}, {}, "服务暂不可用，请稍后手动重试。"),
    (503, {"error_type": "service_unavailable"}, {}, "服务暂不可用，请稍后手动重试。"),  # Only service_busy is busy.
    (503, {"detail": "synthetic server detail"}, {}, "服务暂不可用，请稍后手动重试。"),
    (408, {}, {}, "请求超时，处理可能仍在进行；请稍后手动重试，避免重复提交。"),
    (504, None, {}, "请求超时，处理可能仍在进行；请稍后手动重试，避免重复提交。"),
    (502, {"error_type": "invalid_response"}, {}, "服务返回了无法识别的内容，请稍后手动重试。"),
    (502, {"detail": "proxy words"}, {}, "服务暂时出错，请稍后手动重试。"),
    (500, {"detail": "synthetic server detail"}, {}, "服务暂时出错，请稍后手动重试。"),
])
def test_a_failure_gets_the_pages_line_and_never_a_server_detail_for_5xx_or_429(status, body, headers, line):
    response = (httpx.Response(status, json=body, headers=headers) if body is not None
                else httpx.Response(status, text="synthetic non-JSON error", headers=headers))
    assert failure_detail(response) == line


def test_a_response_the_page_read_as_a_success_has_no_failure_line():
    assert failure_detail(httpx.Response(201, json={"ok": True})) is None
    assert failure_detail(httpx.Response(302, json={"ok": True})) is None
    assert failure_detail(httpx.Response(204)) is None
    assert failure_detail(httpx.Response(202, text="not JSON")) == "服务返回了无法识别的内容，请稍后手动重试。"
