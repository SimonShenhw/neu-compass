"""Cross-check UI history and optimized-run safety without external data.
中文：真实 UI 文本对拍；已发请求后的工具异常也不能丢失 HTTP／日志账目。
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


@pytest.mark.parametrize("chunks,error", [(["Synthetic partial answer"], "upstream_error"), ([], "empty_stream")])
def test_next_turn_history_matches_the_real_ui_generator(chunks, error):
    from app.streamlit_app import stream_assistant
    from eval.route_eval import load_cases, run_eval

    case = copy.deepcopy(next(item for item in load_cases()["cases"] if item["case_id"] == "stream_recovery_good"))
    first = case["turns"][0]
    first["stream"] = {"chunks": chunks, "error": error}
    first["expected"]["error_type"] = "no_answer" if error == "empty_stream" else "upstream_error"
    first["expected_generation"]["verdict"] = "no_answer" if error == "empty_stream" else "stream_error"
    report = run_eval([case])
    turn = report["cases"][0]["turns"][0]
    # Use the actual route error detail by replaying the route with the same script below.
    from fastapi.testclient import TestClient
    from eval.route_world import SyntheticWorld
    import json

    with SyntheticWorld() as world, TestClient(world.app) as client:
        world.set_stream(first["stream"])
        events = [json.loads(line) for line in client.post("/chat", json=turn["request"],
                   headers={"X-Eval-Run": "opt06-ui-parity"}).text.splitlines()]

    class ScriptAPI:
        def chat_stream(self, body):
            yield from events

    ui_text = "".join(stream_assistant(ScriptAPI(), turn["request"], {}))
    assert report["cases"][0]["turns"][1]["request"]["history"][1]["content"] == ui_text


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
