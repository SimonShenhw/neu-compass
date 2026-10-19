"""Review regressions for failure accounting, guarded I/O and real vector dependence.
中文：故障必须可见；不允许评测通过吞掉路由错误或非法访问。
"""

import copy
import json
import sqlite3
import sys

import httpx
import pytest


def first_case():
    from eval.route_eval import load_cases

    case = copy.deepcopy(load_cases()["cases"][0])
    case["turns"][0]["expected"].setdefault("rescue_calls", 0)
    case["turns"][0].setdefault("expected_generation", {"verdict": "pass", "required_signals": [], "forbidden_signals": []})
    return case


def test_unexpected_http_failure_is_not_a_successful_not_applicable(monkeypatch):
    from fastapi.testclient import TestClient
    from eval import route_eval

    monkeypatch.setattr(TestClient, "post", lambda *a, **k: httpx.Response(500, json={"detail": "synthetic failure"}))
    report = route_eval.run_eval([first_case()])
    assert report["status"] == "failed" and report["generation"]["unexpected_http"] == 1
    assert report["route_contract"]["fail"] == 1 and report["expectation_mismatches"] >= 1
    assert route_eval.exit_code(report) == 1


def test_generation_expectations_and_console_exit_are_enforced(tmp_path, monkeypatch, capsys):
    from eval import route_eval
    from scripts import eval_route_offline as cli

    case = first_case()
    case["turns"][0]["expected_generation"]["required_signals"] = ["course_codes_outside_evidence"]
    report = route_eval.run_eval([case])
    assert report["expectation_mismatches"] == 1 and report["status"] == "failed"
    monkeypatch.setattr(route_eval, "run_eval", lambda: report)
    assert cli.main(["--out", str(tmp_path / "out.json")]) == 1
    line = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert line["route_fail"] == 0 and line["expectation_mismatches"] == 1


@pytest.mark.parametrize("change", [{}, {"unexpected_key": 1}, {"notices": "text"}, {"must_include": "neu-cs-9001"},
    {"http_status": True}, {"rescue_calls": -1}, {"matched_via": "typo"}])
def test_invalid_expected_contracts_are_setup_errors(change):
    from eval.route_eval import run_eval

    case = first_case()
    case["turns"][0]["expected"] = {} if not change else {**case["turns"][0]["expected"], **change}
    with pytest.raises(ValueError):
        run_eval([case])


@pytest.mark.parametrize("key,value,reason", [("must_include", ["neu-cs-9002"], "required_hit_missing"),
    ("must_exclude", ["neu-cs-9001"], "forbidden_hit_present"), ("notices", ["not-a-real-notice"], "notices_mismatch"),
    ("matched_via", "context", "matched_via_mismatch"), ("detail_contains", ["nonexistent"], "decision_detail_mismatch")])
def test_each_route_comparison_can_independently_fail(key, value, reason):
    from eval.route_eval import run_eval

    case = first_case()
    case["turns"][0]["expected"][key] = value
    turn = run_eval([case])["cases"][0]["turns"][0]
    assert reason in turn["route_contract"]["reasons"]


def test_world_blocks_both_database_seams_raw_sqlite_and_restores_guards(tmp_path, monkeypatch):
    import api.dependencies as dependencies
    import db.connection as connection
    from eval.route_world import SyntheticWorld

    def outer_trap(*a, **k):
        pytest.fail("real connection seam was reached")

    monkeypatch.setattr(connection, "connect", outer_trap)
    original = dependencies.connect
    with SyntheticWorld() as world:
        for fn in (dependencies.connect, connection.connect):
            with pytest.raises(RuntimeError, match="forbidden"):
                fn("must-not-be-opened.sqlite")
        with pytest.raises(RuntimeError, match="forbidden"):
            sqlite3.connect(f"file:{tmp_path}/absent-dir/absent.sqlite?mode=ro", uri=True)
        assert world.guard.counters["database_attempts"] == 3
        with pytest.raises(RuntimeError, match="forbidden"):
            sys.audit("socket.connect", None, ("127.0.0.1", 1))
        assert world.guard.counters["network_attempts"] == 1
    assert dependencies.connect is original and connection.connect is outer_trap
    with SyntheticWorld() as other:
        assert not any(other.guard.counters.values())


def test_real_model_seams_are_blocked_before_any_provider_call(monkeypatch):
    import api.dependencies as dependencies
    import llm.gemini_client as gemini
    import rag.hyde as hyde
    from eval.route_world import SyntheticWorld

    def outer_trap(*a, **k):
        pytest.fail("provider was reached")

    monkeypatch.setattr(gemini, "generate_text_stream", outer_trap)
    monkeypatch.setattr(dependencies, "generate_text_stream", outer_trap)
    monkeypatch.setattr(hyde, "rescue_expand", outer_trap)
    with SyntheticWorld() as world:
        for fn in (gemini.generate_text_stream, dependencies.generate_text_stream, hyde.rescue_expand):
            with pytest.raises(RuntimeError, match="forbidden"):
                list(fn("synthetic"))
        assert world.guard.counters["model_attempts"] == 3


def test_partial_hard_failures_are_separate_from_complete_answers():
    from eval.route_eval import run_eval

    case = first_case()
    turn = case["turns"][0]
    turn["stream"] = {"chunks": ["neu-cs-9001"], "error": "upstream_error"}
    turn["expected"]["error_type"] = "upstream_error"
    turn["expected_generation"] = {"verdict": "stream_error", "required_signals": ["ids_fail"], "forbidden_signals": []}
    report = run_eval([case])
    assert report["generation"]["partial_hard_fail"] == 1
    assert report["generation"]["checked"] == report["generation"]["hard_fail"] == 0
    assert report["stream_contract"]["pass"] == 1


def test_new_world_and_cases_use_ui_config_and_explicit_provenance():
    from eval.route_eval import run_eval

    report = run_eval()
    assert 25 <= report["index"]["course_count"] <= 30
    assert all(turn["request"]["k"] == 10 for case in report["cases"] for turn in case["turns"])
    assert report["settings"]["rerank_pool_size"]["value"] == 20
    assert report["settings"]["acronym_expansion"]["value"] is True
    assert report["settings"]["blend_alpha"]["source"] == "code_default"
    assert report["settings"]["deployment_verified"] is False
    assert "recall_at_10" in report["route_contract"]["hybrid_metrics"]
    assert report["database"]["query_log_rows"] == report["database"]["http_200_turns"]
    assert not any(report["isolation"].values())
    assert report["expectation_mismatches"] == 0
    assert report["route_contract"]["fail"] == report["stream_contract"]["fail"] == 0


@pytest.mark.parametrize("mode", ["constant", "anti_topic", "disabled"])
def test_vector_required_cases_detect_single_factor_degradation(mode):
    from eval.route_eval import load_cases, run_eval

    cases = [case for case in load_cases()["cases"] if case.get("vector_required")]
    assert len(cases) >= 3
    normal, broken = run_eval(cases), run_eval(cases, vector_mode=mode)
    assert normal["status"] == "complete" and normal["route_contract"]["fail"] == 0
    assert broken["route_contract"]["fail"] > 0 and broken["status"] == "failed"
    assert normal["route_contract"]["vector_required_metrics"]["n"] == len(cases)
    assert normal["case_input_sha256"] == broken["case_input_sha256"]


def test_report_exit_policy_distinguishes_mismatch_and_incomplete():
    from eval.route_eval import exit_code

    assert exit_code({"status": "complete"}) == 0
    assert exit_code({"status": "failed"}) == 1
    assert exit_code({"status": "incomplete"}) == 3
