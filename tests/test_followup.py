"""Tests for rag.followup — the deterministic follow-up (anaphora) detector
behind the /chat conversation-continuity context tier."""

from __future__ import annotations

import pytest

from rag.followup import is_followup_query


@pytest.mark.parametrize("q", [
    "这门课作业量大吗？",
    "那你能给我讲讲这门课大概讲什么内容吗？",
    "它的先修要求是什么",
    "这课难吗",
    "该课的考核方式？",
    "what does this course cover?",
    "is it hard?",
    "how heavy is the workload for that class?",
    "tell me more about the course",
    "这几门课怎么选？both seem interesting",
])
def test_followups_detected(q: str) -> None:
    assert is_followup_query(q) is True


@pytest.mark.parametrize("q", [
    # Names its own course — even with a referent word present.
    "AAI 6620 这门课怎么样？",
    "和 CS 6120 比这门课哪个好",
    "cs5800 难吗",
    # Fresh queries with no referent at all.
    "machine learning for beginners",
    "我想学深度学习选什么课",
    "CS 专业 第一学期选啥",
    "easiest 3-credit ML class",
    # Degenerate inputs.
    "",
    "   ",
])
def test_non_followups_pass_through(q: str) -> None:
    assert is_followup_query(q) is False


def test_referent_without_context_is_callers_problem() -> None:
    """The detector only inspects the text; the route additionally
    requires non-empty context_course_ids before taking the context
    tier. Documenting the contract here."""
    assert is_followup_query("这门课怎么样") is True  # text says follow-up
    # ...but with no context ids the route falls through to the normal
    # pipeline (covered by route-level tests).
