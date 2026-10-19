"""Malformed enum types must be preparation errors, not uncaught TypeError.
中文：输入类型不对时保持明确的 ValueError 契约，不因集合查找抛出意外异常。
"""

import copy

import pytest


@pytest.mark.parametrize("field", ["matched_via", "error_type", "verdict"])
@pytest.mark.parametrize("value", [[], {}])
def test_unhashable_enum_values_are_rejected_cleanly(field, value):
    from eval.route_eval import _validate_cases, load_cases

    cases = copy.deepcopy(load_cases()["cases"][:1])
    turn = cases[0]["turns"][0]
    turn["expected_generation" if field == "verdict" else "expected"][field] = value
    with pytest.raises(ValueError):
        _validate_cases(cases)


def test_ui_k_requires_an_integer_not_an_equal_float():
    from eval.route_eval import _validate_cases, load_cases

    cases = copy.deepcopy(load_cases()["cases"][:1])
    cases[0]["turns"][0]["request"]["k"] = 10.0
    with pytest.raises(ValueError):
        _validate_cases(cases)


@pytest.mark.parametrize("cues,expected", [("hours and difficulty", "difficulty_score"),
                                         ("difficulty and hours", "workload_hours_per_week")])
def test_nearest_field_cue_has_two_recognized_candidates(cues, expected):
    from eval.answer_checks import AnswerContext, check_answer

    context = AnswerContext(lang="en", course_codes=("CS 9001",), unstated=(
        ("CS 9001", "workload_hours_per_week", 4.0), ("CS 9001", "difficulty_score", 4.0)))
    items = check_answer(f"CS 9001 {cues}: 4.", context)["estimates"]
    assert [(item["field"], item["identity"]) for item in items] == [(expected, "resolved")]
