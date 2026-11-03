"""Independent native-I/O, cached-model and HTTP-history review probes.
中文：只构造临时合成文件和内存假模块；不访问真实库、索引或模型。
"""

import copy
import sqlite3
import sys
from types import ModuleType

import pytest


@pytest.mark.parametrize("kind", ["attach", "faiss"])
def test_native_reads_cannot_succeed_with_zero_isolation_counts(tmp_path, monkeypatch, kind):
    import faiss
    import api.routes.chat as chat
    from eval.route_eval import exit_code, load_cases, run_eval

    database, index = tmp_path / "synthetic.sqlite", tmp_path / "synthetic.faiss"
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE synthetic_only(value)")
    faiss.write_index(faiss.IndexFlatIP(2), str(index))
    original = chat.build_answer_evidence

    def native_read(conn, *args, **kwargs):
        if kind == "attach":
            conn.execute("ATTACH DATABASE ? AS forbidden", (str(database),))
        else:
            faiss.read_index(str(index))
        return original(conn, *args, **kwargs)

    monkeypatch.setattr(chat, "build_answer_evidence", native_read)
    report = run_eval(copy.deepcopy(load_cases()["cases"][:1]))
    assert report["status"] == "failed" and exit_code(report) == 1
    assert report["isolation"]["database_attempts" if kind == "attach" else "file_attempts"] == 1


def test_cached_model_module_cannot_construct_a_model(monkeypatch):
    from eval.route_world import SyntheticWorld
    from rag.embedder import BGEM3Embedder

    called = []
    fake = ModuleType("FlagEmbedding")
    fake.BGEM3FlagModel = lambda *args, **kwargs: called.append(True)
    monkeypatch.setitem(sys.modules, "FlagEmbedding", fake)
    with SyntheticWorld() as world:
        with pytest.raises(RuntimeError, match="forbidden"):
            BGEM3Embedder()._load()
        assert called == [] and world.guard.counters["model_attempts"] == 1


def test_same_world_reentry_does_not_replace_the_outer_cleanup_stack():
    import db.connection as connection
    from eval import route_guard
    from eval.route_world import SyntheticWorld

    original, bytecode = connection.connect, sys.dont_write_bytecode
    world = SyntheticWorld()
    with world:
        outer = world.stack
        try:
            with pytest.raises(RuntimeError, match="nesting|reenter"):
                with world:
                    pytest.fail("nested world must not enter")
            assert world.stack is outer
        finally:
            # Cleanup even on the pre-fix failure, without hiding the assertion.
            world.stack = outer
    assert route_guard._ACTIVE is None
    assert connection.connect is original and sys.dont_write_bytecode == bytecode
    with world:
        assert route_guard._ACTIVE is world.guard
    assert route_guard._ACTIVE is None


def first_answered_with(monkeypatch, status, body, headers):
    """run_eval on the first case played twice, its first /chat answered with this response instead of the route's."""
    from eval.route_eval import load_cases, run_eval
    from eval.route_world import SyntheticWorld
    from starlette.responses import JSONResponse, Response

    case = copy.deepcopy(load_cases()["cases"][0])
    case["turns"].append(copy.deepcopy(case["turns"][0]))
    original = SyntheticWorld.__enter__

    def enter(self):
        world = original(self)
        first = True

        @world.app.middleware("http")
        async def injected(request, call_next):
            nonlocal first
            if first:
                first = False
                return (JSONResponse(body, status_code=status, headers=headers) if body is not None
                        else Response("synthetic non-JSON error", status_code=status))
            return await call_next(request)
        return world

    monkeypatch.setattr(SyntheticWorld, "__enter__", enter)
    return run_eval([case])


# The line the Streamlit page showed for each failure (app/api_client.py's ApiError text, equal to the eval's history
# when R8 checked them before deleting app/; tests/test_route_ui.py has the rest of its cases), after the page's
# prefix: 🧭 for a 409's detail, "⚠️ Chat failed:" for the rest.
# 中文：Streamlit 页对每种失败显示的那句话（R8 删 app/ 之前核对过，和评测写进历史的一样），前面是页面加的前缀。
@pytest.mark.parametrize("status,body,headers,shown", [
    (500, {"detail": "synthetic server detail"}, {}, "⚠️ Chat failed: 服务暂时出错，请稍后手动重试。"),
    (503, {"detail": "synthetic server detail", "error_type": "service_busy"}, {"Retry-After": "7"},
     "⚠️ Chat failed: 服务正忙，请7 秒后手动重试。"),
    (404, None, {}, "⚠️ Chat failed: 请求未完成，请稍后手动重试。"),
    (409, {"detail": "synthetic conflict detail"}, {}, "🧭 synthetic conflict detail"),
])
def test_http_failure_history_keeps_what_the_page_showed(monkeypatch, status, body, headers, shown):
    report = first_answered_with(monkeypatch, status, body, headers)
    assert report["cases"][0]["turns"][1]["request"]["history"][1]["content"] == shown
    assert report["status"] == "failed"


def test_a_non_200_success_is_a_harness_error_not_a_failure_line(monkeypatch):
    # The page read a 2xx with JSON as an answer, so the eval has no line for it and stops that turn.
    # 中文：页面把带 JSON 的 2xx 当成功读，评测没有对应的那句话，这一轮记为工具错误。
    report = first_answered_with(monkeypatch, 202, {"ok": True}, {})
    turn = report["cases"][0]["turns"][0]
    assert report["status"] == "incomplete" and turn["error_class"] == "ValueError"
    assert turn["error_detail"] == "non-200 response was not an API failure"
