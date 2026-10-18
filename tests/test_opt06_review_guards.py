"""Additional independent probes for audit visibility, source identity and metric scope.
中文：补上审查变异的独立反例，不以一个总绿色运行替代具名覆盖。
"""

import copy
import hashlib
import json
import sys

import pytest


def first_cases():
    from eval.route_eval import load_cases
    return copy.deepcopy(load_cases()["cases"][:1])


def test_a_blocked_lazy_database_open_is_retained_in_the_failure_report(monkeypatch):
    import api.routes.chat as chat
    import db.connection as connection
    from eval.route_eval import exit_code, run_eval

    def illegal(*a, **k):
        connection.connect("must-not-be-opened.sqlite")

    monkeypatch.setattr(chat, "build_answer_evidence", illegal)
    report = run_eval(first_cases())
    assert report["status"] == "failed" and exit_code(report) == 1
    assert report["isolation"]["database_attempts"] == 1
    assert report["generation"]["unexpected_http"] == 1
    assert report["route_contract"]["fail"] == 1
    assert report["database"]["accounting_errors"]


def test_missing_stream_override_counts_attempt_without_calling_a_provider(monkeypatch):
    import api.dependencies as dependencies
    from eval.route_world import SyntheticWorld
    from eval.route_eval import run_eval

    original = SyntheticWorld.__enter__

    def missing(self):
        result = original(self)
        del result.app.dependency_overrides[dependencies.get_chat_stream_fn]
        return result

    monkeypatch.setattr(SyntheticWorld, "__enter__", missing)
    report = run_eval(first_cases())
    assert report["real_model_calls"] == report["isolation"]["model_attempts"] == 1
    assert report["status"] != "complete"


def test_query_log_tag_guard_has_an_independent_negative_control(monkeypatch):
    import api.routes.chat as chat
    from eval.route_eval import run_eval

    original = chat.log_query

    def untagged(*args, **kwargs):
        kwargs["user_id"] = "not-an-eval-tag"
        return original(*args, **kwargs)

    monkeypatch.setattr(chat, "log_query", untagged)
    report = run_eval(first_cases())
    assert report["status"] == "failed"
    assert report["database"]["query_dml_changes"] == report["database"]["query_log_rows"] == 1
    assert "query_log without eval tag" in report["database"]["accounting_errors"]


def test_filesystem_mutations_are_blocked_without_performing_them():
    from eval.route_world import SyntheticWorld

    with SyntheticWorld() as world:
        with pytest.raises(RuntimeError, match="forbidden"):
            sys.audit("os.mkdir", "synthetic-not-created", 511, -1)
        assert world.guard.counters["file_attempts"] == 1


def test_metrics_have_exact_subset_denominators_and_degradation_loses_actual_hits():
    from eval.route_eval import load_cases, run_eval

    report = run_eval()
    assert report["route_contract"]["hybrid_metrics"]["n"] == 11
    assert report["route_contract"]["vector_required_metrics"]["n"] == 3
    assert report["route_contract"]["lexical_required_metrics"]["n"] == 5
    cases = [item for item in load_cases()["cases"] if item.get("vector_required")]
    for mode in ("constant", "anti_topic", "disabled"):
        broken = run_eval(cases, vector_mode=mode)
        # Round 17 (F25a N1): the trace check is the tie-independent signal for every mode. Candidate loss is asserted
        # only where it does not depend on how FAISS orders exact ties (not for constant query vectors).
        # 中文：第 17 轮：轨迹检查对每种退化都不依赖并列名次；常数模式丢不丢候选取决于并列顺序，不再断言。
        # A disabled vector leg leaves fusion with nothing to fuse, so the trace itself is missing; both fail closed.
        assert all({"vector_top_mismatch", "trace_missing"} & set(actual["turns"][0]["route_contract"]["reasons"])
                   for actual in broken["cases"])
        metrics = broken["route_contract"]["vector_required_metrics"]
        assert 0 <= metrics["recall_at_10"] <= 1 and 0 <= metrics["mrr"] <= 1
        if mode != "constant":
            assert metrics["recall_at_10"] < 1
            assert any(not set(item["turns"][0]["expected"]["must_include"]) <= set(actual["turns"][0]["result_ids"])
                       for item, actual in zip(cases, broken["cases"]))


def test_saved_checker_hash_conflicts_and_layer_are_really_refreshed(tmp_path):
    from eval.answer_checks import AnswerContext, check_answer
    from scripts import eval_answers_live as live
    from tests.test_eval_answers_live import PAYLOADS, QUESTION

    generated = live.run([QUESTION], PAYLOADS, out=tmp_path / "original", runs=1, max_calls=1,
                         stream_fn=lambda prompt: iter(["CS 5200 每周需要 12 小时。 "]))
    assert generated["evidence_layer"] == "live_model"
    generated["answer_checks_sha256"] = "old-checker-sha"
    source = tmp_path / "old.json"
    source.write_text(json.dumps(generated))
    rescored = live.rescore(source, out=tmp_path / "rescored")
    assert rescored["answer_checks_sha256"] == hashlib.sha256((live.PROJECT_ROOT / "eval/answer_checks.py").read_bytes()).hexdigest()
    context = AnswerContext(lang="en", course_codes=("CS 9001", "CS 9002"), conflicts=(("CS 9001", "credits", (3.0, 4.0)),))
    checks = check_answer("CS 9001 has 3 credits. CS 9002 has 4 credits.", context)
    assert checks["conflicts_missing_values"][0]["missing_values"] == [4.0]
    bad = live.context_to_json(context)
    bad["conflicts"] = [["CS 9001", "bad_field", [3.0, 4.0]]]
    assert not live._context_ok(bad)
