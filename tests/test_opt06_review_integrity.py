"""The history the eval sends after a failed stream, and optimized-run safety, without external data.
中文：流失败以后评测发出的历史；已发请求后的工具异常也不能丢失 HTTP／日志账目。
"""

import ast
import copy
from pathlib import Path

import pytest


def test_error_after_http_response_keeps_status_and_query_log_accounting(monkeypatch):
    from eval import route_eval

    original = route_eval.context_from_chat
    calls = 0

    def once(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("synthetic projection failure after HTTP 200")
        return original(*args)

    monkeypatch.setattr(route_eval, "context_from_chat", once)
    report = route_eval.run_eval(route_eval.load_cases()["cases"][:2])
    assert report["status"] == "incomplete" and report["population"]["cases_errored"] == 1
    assert report["cases"][0]["turns"][0]["http_status"] == 200
    assert report["database"]["query_log_rows"] == report["database"]["http_200_turns"] == 2


# What the Streamlit page showed for these two streams (its stream_assistant; equal to the eval's history when R8
# checked them, before deleting app/): the route's error line after whatever had arrived.
# 中文：Streamlit 页对这两种流显示的文字（R8 删 app/ 之前核对过，和评测写进历史的一样）：已收到的部分加上路由的错误句。
@pytest.mark.parametrize("chunks,error,shown", [
    (["Synthetic partial answer"], "upstream_error",
     "Synthetic partial answer\n\n⚠️ 模型服务暂时出错，这条回答没有完成。请稍后再问一次。"),
    ([], "empty_stream", "⚠️ 这次模型没有给出回答，可能被它的安全规则拦下了。换个问法再试试。"),
])
def test_next_turn_history_keeps_what_the_page_showed(chunks, error, shown):
    from eval.route_eval import load_cases, run_eval

    case = copy.deepcopy(next(item for item in load_cases()["cases"] if item["case_id"] == "stream_recovery_good"))
    first = case["turns"][0]
    first["stream"] = {"chunks": chunks, "error": error}
    first["expected"]["error_type"] = "no_answer" if error == "empty_stream" else "upstream_error"
    first["expected_generation"]["verdict"] = "no_answer" if error == "empty_stream" else "stream_error"
    report = run_eval([case])
    assert report["cases"][0]["turns"][1]["request"]["history"][1]["content"] == shown


def test_accounting_and_isolation_do_not_depend_on_python_asserts():
    root = Path(__file__).resolve().parents[1]
    for name in ("eval/route_eval.py", "eval/route_world.py", "eval/route_guard.py"):
        assert not any(isinstance(node, ast.Assert) for node in ast.walk(ast.parse((root / name).read_text())))


def test_output_inside_repository_is_rejected_before_running(monkeypatch):
    from eval import route_eval
    from scripts.eval_route_offline import ROOT, main

    monkeypatch.setattr(route_eval, "run_eval", lambda: pytest.fail("run should not start"))
    assert main(["--out", str(ROOT / "must-not-create-opt06.json")]) == 2
    assert not (ROOT / "must-not-create-opt06.json").exists()
