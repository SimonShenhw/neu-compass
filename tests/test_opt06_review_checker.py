"""Second-round checker regressions: legacy availability, identity and bounded signals.
中文：审查返工先冻结行为断言，不将缺失身份误写成证据为空。
"""

import copy
import json

import pytest

from eval.answer_checks import AnswerContext, check_answer, summarize
from scripts import eval_answers_live as live
from tests.test_eval_answers_live import PAYLOADS, QUESTION


def test_legacy_rescore_does_not_invent_outside_evidence_signals(tmp_path):
    source = tmp_path / "old.json"
    context = {"lang": "en", "allowed_urls": [], "prompt_keys": [], "unstated_values": [12.0]}
    source.write_text(json.dumps({"prompt_version": "4.4", "chat_v4_sha256": "0" * 64,
        "model_calls": 1, "errors": 0, "records": [{"qid": "old", "run": 1,
        "answer": "CS 5200 and CS 5800: reviews report 12 hours per week.", "context": context}]}))
    before = source.read_bytes()
    report = live.rescore(source, out=tmp_path / "new")
    checks = report["records"][0]["checks"]
    assert checks["course_codes_outside_evidence"] is None
    assert checks["estimates"][0]["identity"] == "unavailable"
    assert checks["estimates"][0]["course"] is None
    assert report["evidence_layer"] == "legacy_unknown" and source.read_bytes() == before
    empty = live.build_case({**QUESTION, "course_ids": []}, {})[1]
    assert check_answer("CS 9099 is a match.", empty)["course_codes_outside_evidence"] == ["CS 9099"]


def test_course_identity_does_not_cross_sentence_boundaries():
    context = AnswerContext(lang="en", course_codes=("CS 9001", "CS 9002"),
        unstated=(("CS 9001", "workload_hours_per_week", 12.0), ("CS 9002", "workload_hours_per_week", 12.0)))
    items = check_answer("CS 9001 takes 12 hours. It takes 12 hours per week.", context)["estimates"]
    assert [(item["course"], item["identity"]) for item in items] == [
        ("CS 9001", "resolved"), (None, "course_unresolved")]


def test_field_mismatch_single_field_fallback_and_nearest_cue():
    workload = AnswerContext(lang="en", course_codes=("CS 9001",),
        unstated=(("CS 9001", "workload_hours_per_week", 4.0),))
    assert check_answer("CS 9001 difficulty is 4/5.", workload)["estimates"] == []
    assert check_answer("CS 9001 recorded number is 4.", workload)["estimates"][0]["field"] == "workload_hours_per_week"
    both = AnswerContext(lang="en", course_codes=("CS 9001",), unstated=(
        ("CS 9001", "workload_hours_per_week", 4.0), ("CS 9001", "difficulty_score", 4.0)))
    assert check_answer("CS 9001 workload and difficulty: 4.", both)["estimates"][0]["field"] == "difficulty_score"
    unresolved = check_answer("CS 9001 recorded number is 4.", both)
    assert unresolved["estimates"][0]["identity"] == "field_unresolved"
    assert summarize([unresolved])["estimates_identity_unresolved"] == 1


def test_unknown_course_is_not_assigned_to_the_single_evidence_course():
    context = AnswerContext(lang="en", course_codes=("CS 9001",),
        unstated=(("CS 9001", "workload_hours_per_week", 12.0),))
    result = check_answer("CS 6140 takes 12 hours per week.", context)
    assert result["estimates"][0]["course"] is None
    assert result["estimates"][0]["identity"] == "course_unresolved"
    assert result["course_codes_outside_evidence"] == ["CS 6140"]


def test_abbreviated_second_course_is_not_silently_assigned():
    context = AnswerContext(lang="en", course_codes=("CS 9001",),
        unstated=(("CS 9001", "workload_hours_per_week", 12.0),))
    result = check_answer("CS 9001 and 9002 take 12 hours per week.", context)
    assert result["course_codes_outside_evidence"] == ["CS 9002"]
    assert result["estimates"][0]["course"] is None


@pytest.mark.parametrize("text", ["学分为 4。", "CS 9001 有 4 次作业。", "CS 9001: 4%.",
    "CS 9001 GPA 4.0.", "CS 9001 date 2026-4-1.", "CS 9001 requires 4 courses.",
    "CS 9001 requires 4 classes.", "CS 9001 requires 4 prerequisites."])
def test_non_estimate_numbers_do_not_use_the_single_field_fallback(text):
    context = AnswerContext(lang="en", course_codes=("CS 9001",),
        unstated=(("CS 9001", "difficulty_score", 4.0),))
    assert check_answer(text, context)["estimates"] == []


def test_conflict_signals_skip_unmentioned_courses_and_accept_sentence_final_numbers():
    context = AnswerContext(lang="en", course_codes=("CS 9005", "CS 9009"),
        conflicts=(("CS 9005", "credits", (3.0, 4.0)),))
    assert check_answer("CS 9009 is the graph alternative.", context)["conflicts_missing_values"] == []
    assert check_answer("CS 9005 record lists 3; the catalog lists 4.", context)["conflicts_missing_values"] == []
    assert check_answer("CS 9005 has 3 credits.", context)["conflicts_missing_values"][0]["missing_values"] == [4.0]


def test_record_attribution_is_clause_local_and_not_cut_off_by_twenty_characters():
    context = AnswerContext(lang="en", course_codes=("CS 9006",),
        unstated=(("CS 9006", "workload_hours_per_week", 12.0),))
    good = "CS 9006 has a recorded workload of 12 hours, but the quote says about 6 hours; the sources disagree."
    assert check_answer(good, context)["estimates"][0]["kind"] == "attributed to the record"
    other_clause = "CS 9006 has a recorded workload; reviews report 12 hours per week."
    assert check_answer(other_clause, context)["estimates"][0]["kind"] == "AS REVIEWER-REPORTED"


def test_conflicts_read_all_supported_values_and_ignore_lecture_duration():
    item = {"field": "workload_hours_per_week", "supported_value": 12.0, "quote": "3 hours of lecture"}
    records = [{"primary_code": "CS 9001", "recorded_metadata": {"workload_hours_per_week": 12.0},
        "answer_evidence": {"catalog": None, "field_evidence": [item]}}]
    assert live.conflict_values(records) == ()
    records[0]["answer_evidence"]["field_evidence"].append({**item, "supported_value": 8.0, "quote": "Heavy work"})
    assert live.conflict_values(records) == (("CS 9001", "workload_hours_per_week", (8.0, 12.0)),)


def test_legacy_and_identified_estimate_forms_both_remain_covered():
    legacy = AnswerContext(lang="en", unstated_values=(4.0, 12.0))
    text = "The workload is estimated at 12 hours a week. Reviews report a difficulty of 4.0/5."
    assert {item["value"]: item["kind"] for item in check_answer(text, legacy)["estimates"]} == {
        12.0: "qualified as estimate", 4.0: "AS REVIEWER-REPORTED"}
    assert check_answer("Reviews report 4 courses.", legacy)["estimates"][0]["identity"] == "unavailable"
    _, context = live.build_case(QUESTION, PAYLOADS)
    assert context.unstated_values == (4.0, 12.0)
    copied = copy.deepcopy(live.context_to_json(context))
    assert live.context_from_json(copied) == context
    with_conflict = AnswerContext(lang="en", course_codes=("CS 9001",), conflicts=(("CS 9001", "credits", (3.0, 4.0)),))
    assert live.context_from_json(live.context_to_json(with_conflict)) == with_conflict
