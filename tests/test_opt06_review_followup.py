"""Read-only review follow-ups: weekly units and numeric ranges stay visible.
中文：独立复核发现的回归先留红色证据，不放宽已有的 lecture／日期反例。
"""

import pytest

from eval.answer_checks import AnswerContext, check_answer
from scripts.eval_answers_live import conflict_values


@pytest.mark.parametrize("quote", ["每周 8 小时", "8 hours weekly", "8 hrs per week", "8 小时/周"])
def test_weekly_conflicts_keep_prefix_and_suffix_units(quote):
    records = [{"primary_code": "CS 9001", "recorded_metadata": {"workload_hours_per_week": 12.0},
        "answer_evidence": {"catalog": None, "field_evidence": [
            {"field": "workload_hours_per_week", "supported_value": 12.0, "quote": quote}]}}]
    assert conflict_values(records) == (("CS 9001", "workload_hours_per_week", (8.0, 12.0)),)


@pytest.mark.parametrize("text", ["12-15", "10-12", "12–15", "10–12", "12—15", "10—12"])
def test_workload_ranges_do_not_look_like_dates(text):
    context = AnswerContext(lang="en", course_codes=("CS 9001",),
        unstated=(("CS 9001", "workload_hours_per_week", 12.0),))
    estimates = check_answer(f"CS 9001 reviews report {text} hours per week.", context)["estimates"]
    assert [(item["value"], item["kind"], item["course"], item["field"]) for item in estimates] == [
        (12.0, "AS REVIEWER-REPORTED", "CS 9001", "workload_hours_per_week")]


@pytest.mark.parametrize("date", ["2026-4-12", "2026/4/12", "4-12-2026", "4/12/2026"])
def test_complete_numeric_dates_remain_non_estimates(date):
    context = AnswerContext(lang="en", course_codes=("CS 9001",),
        unstated=(("CS 9001", "workload_hours_per_week", 12.0),))
    assert check_answer(f"CS 9001 review was posted on {date}.", context)["estimates"] == []


def test_lecture_duration_remains_non_weekly_even_with_another_weekly_fact():
    records = [{"primary_code": "CS 9001", "recorded_metadata": {"workload_hours_per_week": 12.0},
        "answer_evidence": {"catalog": None, "field_evidence": [{"field": "workload_hours_per_week",
            "supported_value": 12.0, "quote": "3 hours of lecture; total workload is 12 hours weekly."}]}}]
    assert conflict_values(records) == ()
