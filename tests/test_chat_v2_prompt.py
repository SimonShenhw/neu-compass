"""Unit tests for llm.prompts.chat_v2 — program-aware course advisor prompt.

We don't drive Gemini here (that's covered by the route-level tests). These
tests pin the prompt structure: required instruction lines, course-list
formatting, version sentinel, etc. If a future edit accidentally drops a
v2-specific rule, these tests scream loudly.
"""

from __future__ import annotations

from llm.prompts.chat_v2 import (
    PROMPT_TEMPLATE,
    PROMPT_VERSION,
    build_prompt,
    format_courses_block,
)
from rag.retriever import SearchHit
from schemas.course import Course, DeliveryMode


def _hit(code: str, name: str, **kwargs) -> SearchHit:
    """Tiny factory matching how the route assembles SearchHit."""
    cid = "c-" + code.lower().replace(" ", "-")
    return SearchHit(
        course=Course(course_id=cid, primary_code=code, primary_name=name, **kwargs),
        score=0.5,
    )


# === Version sentinel ===


def test_prompt_version_is_2_0() -> None:
    assert PROMPT_VERSION == "2.0"


# === Course block formatting (carries over from v1) ===


def test_empty_hits_renders_no_match_marker() -> None:
    """Empty list must render an explicit '(no matches found in catalog)'
    line so the LLM sees a definite signal — not just a blank space."""
    block = format_courses_block([])
    assert "no matches" in block.lower()


def test_course_block_includes_code_name_term_credits() -> None:
    block = format_courses_block([
        _hit("AAI 5015", "Mathematical Concepts", term="Fall 2026", credits=3),
    ])
    assert "AAI 5015" in block
    assert "Mathematical Concepts" in block
    assert "Fall 2026" in block
    assert "3 credits" in block


def test_course_block_omits_optional_fields_when_none() -> None:
    """term/credits/delivery_mode being None shouldn't render 'None' or
    leave a stray separator."""
    block = format_courses_block([_hit("AAI 6640", "Applied Deep Learning")])
    assert "AAI 6640" in block
    assert "None" not in block
    assert "·  ·" not in block  # no empty-cell artifact


def test_course_block_renders_delivery_mode_human_readable() -> None:
    block = format_courses_block([
        _hit("AAI 6610", "Applied ML", delivery_mode=DeliveryMode.IN_PERSON),
    ])
    assert "in person" in block  # underscore stripped


# === v2-specific instruction rules ===


def test_prompt_template_contains_grounding_hard_rule() -> None:
    """The 'do not invent courses' rule is the v1 baseline; v2 strengthens
    it by forbidding fallback recommendations from unrelated departments."""
    assert "Only cite courses that appear verbatim" in PROMPT_TEMPLATE
    assert "Do NOT invent courses" in PROMPT_TEMPLATE


def test_prompt_template_contains_program_prefix_discipline() -> None:
    """The core fix: when the student names a program prefix (AAI / CS / ...),
    only courses with that prefix may be recommended. v1 said 'suggest
    closest alternatives' which produced cross-discipline noise."""
    assert "Program-prefix discipline" in PROMPT_TEMPLATE
    assert "AAI" in PROMPT_TEMPLATE
    assert "Cross-discipline recommendations are FORBIDDEN" in PROMPT_TEMPLATE


def test_prompt_template_contains_foundational_level_heuristic() -> None:
    """5xxx is foundational, 6xxx intermediate, 7xxx advanced — for
    'first-semester / 第一学期' questions the LLM should prefer 5xxx."""
    assert "5xxx" in PROMPT_TEMPLATE
    assert "6xxx" in PROMPT_TEMPLATE
    assert "first-semester" in PROMPT_TEMPLATE
    assert "第一学期" in PROMPT_TEMPLATE


def test_prompt_template_contains_honest_no_match_phrase() -> None:
    """When retrieved list lacks a prefix-matching course, the LLM must
    SAY so cleanly rather than fall back to recommending whatever's
    closest. Pin the exact phrase as a regression hook."""
    assert "I couldn't find a matching course" in PROMPT_TEMPLATE
    assert "There are no <PREFIX> courses" in PROMPT_TEMPLATE


def test_prompt_template_preserves_language_match_rule() -> None:
    """Bilingual NEU users — the LLM must answer in the same language as
    the question. Pin so future edits don't accidentally drop this."""
    assert "Match the language" in PROMPT_TEMPLATE


# === build_prompt integration ===


def test_build_prompt_substitutes_query_and_hits() -> None:
    """build_prompt must template the query and the formatted course list
    into the {query} and {courses} placeholders respectively."""
    prompt = build_prompt(
        "那AAI 6640这门课能给我说说吗",
        [_hit("AAI 6640", "Applied Deep Learning")],
    )
    assert "那AAI 6640这门课能给我说说吗" in prompt
    assert "AAI 6640 — Applied Deep Learning" in prompt


def test_build_prompt_with_no_hits_still_includes_no_match_marker() -> None:
    """Empty hits → the courses block says '(no matches found in catalog)'
    — the LLM is expected to honestly report that fact in the answer."""
    prompt = build_prompt("AAI 专业第一学期推荐", [])
    assert "AAI 专业第一学期推荐" in prompt
    assert "no matches" in prompt.lower()
