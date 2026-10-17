"""OPT-06 route evaluation contracts: in-memory synthetic data and scripted streams only.

中文：合成世界走真实路由；检索、生成与分母分别守约，不证明生产质量。
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CATEGORIES = {"alias_hybrid", "filters", "followup", "program", "numeric_identity",
              "source_conflict", "no_results", "stream_recovery"}


@pytest.fixture(scope="module")
def report():
    from eval.route_eval import run_eval

    return run_eval()


def case(report, name):
    return next(item for item in report["cases"] if item["case_id"] == name)


def test_case_set_covers_all_categories_with_good_and_bad_answers():
    from eval.route_eval import load_cases

    bundle = load_cases()
    assert 25 <= len(bundle["cases"]) <= 35
    assert {item["category"] for item in bundle["cases"]} == CATEGORIES
    assert len({item["case_id"] for item in bundle["cases"]}) == len(bundle["cases"])
    for category in CATEGORIES:
        assert {item["answer_kind"] for item in bundle["cases"] if item["category"] == category} >= {"good", "bad"}


def test_all_cases_and_turns_stay_in_the_denominator(report):
    from eval.route_eval import load_cases

    cases = load_cases()["cases"]
    population = report["population"]
    assert population["cases_planned"] == population["cases_attempted"] == len(cases) == len(report["cases"])
    assert population["cases_planned"] == sum(population[key] for key in (
        "cases_completed", "cases_errored", "cases_not_attempted"))
    assert population["turns_planned"] == population["turns_attempted"] == sum(len(item["turns"]) for item in cases)
    retrieval, generation = report["retrieval"], report["generation"]
    assert retrieval["planned"] == retrieval["scored"] + retrieval["not_scored"] == population["turns_planned"]
    assert retrieval["scored"] == retrieval["pass"] + retrieval["fail"]
    assert generation["planned"] == sum(generation[name] for name in (
        "checked", "stream_error", "no_answer", "not_applicable", "not_checked"))
    assert generation["planned"] == population["turns_planned"] and generation["hard_fail"] <= generation["checked"]
    assert set(report["retrieval"]["by_category"]) == CATEGORIES
    assert all(turn["retrieval"]["verdict"] == "pass" for item in report["cases"] for turn in item["turns"])


def test_stream_errors_and_http_decisions_do_not_disappear(report):
    assert case(report, "stream_partial")["turns"][0]["generation"]["verdict"] == "stream_error"
    assert case(report, "stream_partial")["turns"][0]["answer"] == "Synthetic partial answer"
    assert case(report, "stream_empty")["turns"][0]["generation"]["verdict"] == "no_answer"
    assert case(report, "program_ambiguous")["turns"][0]["generation"]["verdict"] == "not_applicable"
    assert case(report, "program_missing")["turns"][0]["http_status"] == 404
    assert report["generation"]["stream_error"] >= 2 and report["generation"]["not_applicable"] >= 2


def test_retrieval_and_generation_are_independent(report):
    from eval.route_eval import load_cases, run_eval

    leaked = case(report, "alias_bad")["turns"][0]
    assert leaked["retrieval"]["verdict"] == "pass" and leaked["generation"]["verdict"] == "hard_fail"
    altered = copy.deepcopy(load_cases()["cases"][0])
    altered["turns"][0]["expected"]["exact_ids"] = ["neu-cs-9002"]
    result = run_eval([altered])["cases"][0]["turns"][0]
    assert result["retrieval"]["verdict"] == "fail" and result["generation"]["verdict"] == "pass"


def test_a_forbidden_actual_hit_fails_even_when_required_hits_match():
    from eval.route_eval import load_cases, run_eval

    altered = copy.deepcopy(load_cases()["cases"][0])
    altered["turns"][0]["expected"]["must_exclude"] = ["neu-cs-9001"]
    turn = run_eval([altered])["cases"][0]["turns"][0]
    assert turn["result_ids"] == ["neu-cs-9001"] and turn["retrieval"]["verdict"] == "fail"


def test_layer_and_source_identities_are_explicit_and_cannot_be_mixed(report):
    from eval.route_eval import summarize_reports

    assert report["evidence_layer"] == "offline_synthetic"
    assert report["real_api_calls"] == report["real_model_calls"] == 0
    assert report["production_quality_verified"] is False and report["data_kind"] == "synthetic"
    assert len(report["world_sha256"]) == len(report["case_file_sha256"]) == len(report["answer_checks_sha256"]) == 64
    assert len(report["code_files_sha256"]) >= 7 and report["checker_version"]
    assert report["index"]["manifest"] is None
    assert summarize_reports([report, report])["cases_planned"] == 2 * report["population"]["cases_planned"]
    with pytest.raises(ValueError, match="layer"):
        summarize_reports([report, {**report, "evidence_layer": "live_model"}])
    with pytest.raises(ValueError):
        summarize_reports([{**report, "real_model_calls": 1}])


def test_synthetic_retrieval_has_discrimination_and_real_exclusions(report):
    from eval.route_world import SyntheticWorld

    with SyntheticWorld() as world:
        courses = world.conn.execute("SELECT primary_code,primary_name FROM courses").fetchall()
        assert 8 <= len(courses) <= 12
        assert all(row[1].startswith("Synthetic") and 9001 <= int(row[0].split()[1]) <= 9099 for row in courses)
        assert world.app.state.faiss_index is not None
        digest = world.world_sha256
    with SyntheticWorld() as other:
        assert digest == other.world_sha256
    filtered = case(report, "filter_credits")["turns"][0]
    assert "neu-ds-9007" not in filtered["result_ids"] and "neu-cs-9001" in filtered["result_ids"]
    hybrid = case(report, "hybrid_good")["turns"][0]
    assert len(hybrid["result_ids"]) < len(courses) and hybrid["result_ids"][0] == "neu-cs-9001"
    assert report["retrieval"]["hybrid_metrics"]["n"] > 0
    assert 0 <= report["retrieval"]["hybrid_metrics"]["recall_at_k"] <= 1
    assert 0 <= report["retrieval"]["hybrid_metrics"]["mrr"] <= 1


def test_followup_and_failure_recovery_use_current_turn_evidence(report):
    turns = case(report, "followup_good")["turns"]
    assert turns[1]["matched_via"] == "context" and turns[1]["result_ids"] == turns[0]["result_ids"]
    assert turns[1]["request"]["context_course_ids"] == turns[0]["result_ids"]
    switched = case(report, "followup_switch")["turns"]
    assert switched[1]["matched_via"] != "context" and switched[1]["result_ids"] != switched[0]["result_ids"]
    recovery = case(report, "stream_recovery_good")["turns"]
    assert recovery[0]["generation"]["verdict"] == "stream_error"
    assert recovery[1]["result_ids"] == recovery[0]["result_ids"]
    assert recovery[1]["request"]["history"][1]["content"].startswith("Synthetic partial answer")
    assert "⚠️ 提示" in recovery[1]["request"]["history"][1]["content"]


def test_context_from_actual_prompt_matches_fixed_evidence_for_multiple_courses():
    from fastapi.testclient import TestClient

    from eval.route_eval import context_from_chat
    from eval.route_world import SyntheticWorld
    from scripts.eval_answers_live import build_case

    with SyntheticWorld() as world, TestClient(world.app) as client:
        world.set_stream({"chunks": ["Synthetic answer"]})
        response = client.post("/chat", json={"query": "CS 9001 CS 9002", "k": 5}, headers={"X-Eval-Run": "opt06-parity"})
        meta = response.json() if response.status_code != 200 else json.loads(response.text.splitlines()[0])
        assert response.status_code == 200 and len(meta["results"]) == 2
        ids = [item["course_id"] for item in meta["results"]]
        question = {"qid": "parity", "query": "CS 9001 CS 9002", "lang": "zh", "course_ids": ids,
                    "route": "alias", "notices": []}
        payloads = {cid: client.get(f"/course/{cid}").json() for cid in ids}
        _, fixed = build_case(question, payloads)
        actual = context_from_chat(meta, world.prompts[-1], "zh")
        assert actual == fixed and set(actual.course_codes) == {"CS 9001", "CS 9002"}


def test_real_database_connection_is_never_used_and_only_eval_logs_change(monkeypatch, report):
    import api.dependencies as dependencies
    from eval.route_eval import load_cases, run_eval

    monkeypatch.setattr(dependencies, "connect", lambda *args, **kwargs: pytest.fail("real database"))
    isolated = run_eval(load_cases()["cases"][:2])
    for result in (isolated, report):
        assert result["database"]["non_query_tables_unchanged"] is True
        assert result["database"]["query_log_rows"] == result["database"]["query_dml_changes"]
        assert all(tag.startswith("eval:opt06-") for tag in result["database"]["query_log_user_ids"])


def test_an_unexpected_turn_error_is_recorded_and_later_cases_still_run(monkeypatch):
    from eval import route_eval

    original = route_eval.execute_turn
    calls = 0

    def failing(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("synthetic harness failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(route_eval, "execute_turn", failing)
    result = route_eval.run_eval(route_eval.load_cases()["cases"][:2])
    assert len(result["cases"]) == result["population"]["cases_attempted"] == 2
    assert result["population"]["cases_errored"] == 1 and result["population"]["cases_completed"] == 1
    assert result["cases"][0]["turns"][0]["error_type"] == "harness_error"
    assert result["generation"]["not_checked"] == result["retrieval"]["not_scored"] == 1
    assert result["cases"][1]["turns"][0]["retrieval"]["verdict"] == "pass"


@pytest.mark.parametrize("text", ["CS9002每周需要12小时。", "这门CS9002每周需要12小时。", "cs9002每周需要12小时。"])
def test_course_identity_accepts_chinese_adjacency_and_case_without_cross_sentence_inheritance(text):
    from eval.answer_checks import AnswerContext, check_answer

    context = AnswerContext(lang="zh", course_codes=("CS 9001", "CS 9002"),
                            unstated=(("CS 9002", "workload_hours_per_week", 12.0),))
    assert check_answer(text, context)["estimates"][0]["identity"] == "resolved"
    assert check_answer(text, context)["estimates"][0]["course"] == "CS 9002"


def test_cli_has_only_out_and_never_overwrites_existing_output(tmp_path):
    from scripts.eval_route_offline import main

    out = tmp_path / "route.json"
    assert main(["--out", str(out)]) == 0
    data = out.read_bytes()
    assert json.loads(data)["evidence_layer"] == "offline_synthetic"
    assert main(["--out", str(out)]) == 2 and out.read_bytes() == data
    for args in ([], ["--out", str(tmp_path / "other.json"), "--api-base", "http://example.invalid"]):
        with pytest.raises(SystemExit) as error:
            main(args)
        assert error.value.code == 2


def test_offline_cli_is_blocked_from_network_models_real_sqlite_and_external_writes(tmp_path):
    code = r'''
import importlib.abc, os, pathlib, runpy, sys
output = pathlib.Path(sys.argv[2]).resolve()
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'torch', 'transformers', 'FlagEmbedding', 'sentence_transformers', 'google', 'openvino', 'onnxruntime'}:
            raise RuntimeError('forbidden_model_import')
sys.meta_path.insert(0, Block())
def audit(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system'}:
        raise RuntimeError('forbidden_external_action')
    if event == 'sqlite3.connect' and args[0] != ':memory:':
        raise RuntimeError('forbidden_database')
    if event == 'open':
        path, mode, flags = args
        if isinstance(path, (str, bytes)):
            target = pathlib.Path(os.fsdecode(path)).resolve()
            if target.name == '.env' or target.name.startswith('.env.'):
                raise RuntimeError('forbidden_env')
            writing = (mode and any(c in mode for c in 'wax+')) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
            if writing and target != output:
                raise RuntimeError('forbidden_write')
sys.addaudithook(audit)
script = sys.argv[1]
sys.argv = [script, '--out', str(output)]
runpy.run_path(script, run_name='__main__')
'''
    result = subprocess.run([sys.executable, "-B", "-c", code, str(ROOT / "scripts/eval_route_offline.py"),
                             str(tmp_path / "offline.json")], cwd=tmp_path, capture_output=True, text=True,
                            timeout=90, env={**os.environ, "GEMINI_API_KEY": "ci-placeholder-not-a-secret",
                                             "PYTHONDONTWRITEBYTECODE": "1"})
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads((tmp_path / "offline.json").read_text(encoding="utf-8"))
    assert data["real_model_calls"] == data["real_api_calls"] == 0
    assert sorted(path.name for path in tmp_path.iterdir()) == ["offline.json"]
