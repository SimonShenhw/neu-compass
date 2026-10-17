"""OPT-06 C-1: course/field identity and non-destructive rescoring; synthetic evidence only.

中文：数值归属和不可覆盖的重评契约；不联网、不调用模型。
"""

from __future__ import annotations

import hashlib
import json

import pytest

from eval import answer_checks as checker
from scripts import eval_answers_live as live
from tests.test_eval_answers_live import PAYLOADS, QUESTION


def test_same_value_is_attributed_per_course():
    _, context = live.build_case(QUESTION, PAYLOADS)
    assert checker.check_answer("CS 5800 的评价说每周大约 12 小时。", context)["estimates"] == []
    items = checker.check_answer("CS5200 的评价说每周大约 12 小时。", context)["estimates"]
    assert [(item["course"], item["field"], item["value"], item["identity"]) for item in items] == [
        ("CS 5200", "workload_hours_per_week", 12.0, "resolved")]


def test_a_count_is_not_a_difficulty_estimate():
    _, context = live.build_case(QUESTION, PAYLOADS)
    assert checker.check_answer("CS 5200 的评价说推荐先修 4 门课。", context)["estimates"] == []
    items = checker.check_answer("CS 5200 的评价说难度 4.0/5。", context)["estimates"]
    assert [(item["course"], item["field"]) for item in items] == [("CS 5200", "difficulty_score")]


@pytest.mark.parametrize("text,identity", [
    ("每周需要 12 小时。", "course_unresolved"),
    ("CS 5800 和 CS 5200 每周需要 12 小时。", "course_unresolved"),
])
def test_ambiguous_course_identity_is_visible_not_silently_assigned(text, identity):
    _, context = live.build_case(QUESTION, PAYLOADS)
    checks = checker.check_answer(text, context)
    assert checks["estimates"][0]["identity"] == identity
    assert checker.summarize([checks])["estimates_identity_unresolved"] == 1


def test_single_course_identity_and_field_units_are_separate():
    context = checker.AnswerContext(lang="en", course_codes=("CS 9001",),
                                    unstated=(("CS 9001", "workload_hours_per_week", 4.0),
                                              ("CS 9001", "difficulty_score", 4.0)))
    for text, field in (("It takes 4 hours per week.", "workload_hours_per_week"),
                        ("The difficulty is 4/5.", "difficulty_score")):
        items = checker.check_answer(text, context)["estimates"]
        assert len(items) == 1 and items[0]["field"] == field and items[0]["identity"] == "resolved"
    assert checker.check_answer("The number is 4.", context)["estimates"][0]["identity"] == "field_unresolved"


def test_summary_counts_unattributed_estimates_and_report_table(tmp_path):
    report = live.run([QUESTION], PAYLOADS, out=tmp_path, runs=1, max_calls=1,
                      stream_fn=lambda prompt: iter(["CS 5200 每周需要 12 小时。"] ))
    assert report["summary"]["estimates_by_kind"]["unattributed"] == 1
    assert "unattributed" in (tmp_path / "summary.md").read_text(encoding="utf-8")


def test_results_record_checker_identity(tmp_path):
    report = live.run([QUESTION], PAYLOADS, out=tmp_path, runs=1, max_calls=1, stream_fn=None)
    assert report["checker_version"] == checker.CHECKER_VERSION
    assert report["answer_checks_sha256"] == hashlib.sha256(live.PROJECT_ROOT.joinpath("eval/answer_checks.py").read_bytes()).hexdigest()
    assert report["evidence_layer"] == "live_api"


def test_no_match_block_and_empty_build_case_are_supported():
    assert live.unstated_values("(no matches found in catalog)") == ()
    _, context = live.build_case({**QUESTION, "course_ids": []}, {})
    assert context.course_codes == context.unstated == context.unstated_values == ()


def test_rescore_writes_new_files_preserving_original_verdicts(tmp_path):
    original, target = tmp_path / "original", tmp_path / "rescored"
    live.run([QUESTION], PAYLOADS, out=original, runs=1, max_calls=1,
             stream_fn=lambda prompt: iter(["CS 5200 每周需要 12 小时。"] ))
    source = original / "results.json"
    report = json.loads(source.read_text(encoding="utf-8"))
    report["checker_version"] = "previous-checker"
    report["records"][0]["checks"]["sentinel_original_verdict"] = True
    source.write_text(json.dumps(report), encoding="utf-8")
    before = {name: (original / name).read_bytes() for name in ("results.json", "summary.md")}
    assert live.main(["--rescore", str(source), "--out", str(target)]) == 0
    assert all((original / name).read_bytes() == data for name, data in before.items())
    new = json.loads((target / "results.json").read_text(encoding="utf-8"))
    assert new["rescore_of"] == {"path": str(source), "sha256": hashlib.sha256(before["results.json"]).hexdigest(),
                                 "checker_version_before": "previous-checker"}
    assert new["checker_version_after"] == new["checker_version"] == checker.CHECKER_VERSION
    assert "sentinel_original_verdict" not in new["records"][0]["checks"]
    assert live.main(["--rescore", str(source), "--out", str(target)]) == 2
    assert live.main(["--rescore", str(source)]) == 2


def test_old_contexts_still_rescore_with_unavailable_identity(tmp_path):
    source = tmp_path / "old.json"
    source.write_text(json.dumps({"prompt_version": "4.4", "chat_v4_sha256": "0" * 64,
        "model_calls": 1, "errors": 0, "records": [{"qid": "old", "run": 1,
        "answer": "Reviews report 12 hours per week.", "context": {
            "lang": "en", "allowed_urls": [], "prompt_keys": [], "unstated_values": [12.0]}}]}), encoding="utf-8")
    before = source.read_bytes()
    assert live.main(["--rescore", str(source), "--out", str(tmp_path / "new")]) == 0
    new = json.loads((tmp_path / "new/results.json").read_text(encoding="utf-8"))
    assert new["records"][0]["checks"]["estimates"][0]["identity"] == "unavailable"
    assert new["rescore_of"]["checker_version_before"] is None
    assert source.read_bytes() == before


@pytest.mark.parametrize("extra", [
    {"course_codes": "CS 9001"}, {"course_codes": [1]}, {"unstated": [["CS 9001", "bad", 12]]},
    {"unstated": [["CS 9001", "difficulty_score", True]]}, {"unstated": [["CS 9001", "difficulty_score"]]},
])
def test_bad_identity_contexts_are_rejected(extra):
    assert not live._context_ok({"lang": "en", "allowed_urls": [], "prompt_keys": [], "unstated_values": [], **extra})


def test_unknown_codes_and_conflicting_values_are_signals_not_hard_failures():
    context = checker.AnswerContext(lang="en", course_codes=("CS 9001",),
                                    conflicts=(("CS 9001", "credits", (3.0, 4.0)),))
    bad = checker.check_answer("CS 9001 has 3 credits. CS 9002 is another option.", context)
    assert bad["course_codes_outside_evidence"] == ["CS 9002"]
    assert bad["conflicts_missing_values"][0]["missing_values"] == [4.0]
    assert not any(bad[name] for name in checker.HARD_FAILURES)
    good = checker.check_answer("CS9001 has 3 credits in the record and 4 credits in the catalog.", context)
    assert good["conflicts_missing_values"] == good["course_codes_outside_evidence"] == []
