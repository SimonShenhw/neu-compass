"""Tests for llm.prompts.extract_v1_1 — pure template, no LLM calls.

Mirrors test_extract_prompt.py (v1.0) plus checks the v1.1-specific
strengthening: CRITICAL block, Bad/Good few-shot examples, and the
"leave empty rather than invent" fallback. PLAN v2.3 §3.3 — these
invariants are what we changed v1.0 → v1.1 for; if they regress, the
CS 5200 enrichment failure mode comes back.
"""

from __future__ import annotations

from llm.formatter import SourceDocument, format_sources
from llm.prompts.extract_v1_1 import (
    PROMPT_TEMPLATE,
    PROMPT_VERSION,
    build_prompt,
)


def test_prompt_version_bumped_to_1_1() -> None:
    assert PROMPT_VERSION == "1.1"


def test_build_prompt_substitutes_sources() -> None:
    sources_xml = format_sources([
        SourceDocument(source_id="syl", source_type="syllabus", content="AAI 6600"),
    ])
    result = build_prompt(sources_xml)
    assert "AAI 6600" in result
    assert sources_xml in result


def test_template_uses_sources_placeholder() -> None:
    assert "{sources}" in PROMPT_TEMPLATE


def test_critical_block_present() -> None:
    """v1.1 hoisted the evidence requirement into a CRITICAL block at the top."""
    p = build_prompt("...")
    assert "CRITICAL" in p
    # Evidence-required field list must be enumerated
    for soft_field in (
        "difficulty_score",
        "workload_hours_per_week",
        "skill_tags",
        "career_relevance",
        "controversial_signals",
    ):
        assert soft_field in p


def test_few_shot_examples_present() -> None:
    """The CS 5200 failure mode (non-empty soft, empty evidence) must be shown
    as a Bad example so the LLM has an explicit anchor."""
    p = build_prompt("...")
    assert "Bad" in p
    assert "Good" in p
    # The exact bad shape that tripped the validator on CS 5200:
    assert '"skill_tags"' in p
    assert '"evidence_snippets": []' in p
    # The matching good shape:
    assert '"field": "skill_tags"' in p


def test_leave_empty_fallback_present() -> None:
    """Explicit "if no evidence, leave empty" rule prevents the LLM from
    inventing soft values to fill perceived gaps."""
    p = build_prompt("...")
    assert "leave the soft field empty" in p.lower() or "leave empty" in p.lower()
    assert "Do NOT invent" in p


def test_field_name_must_match_verbatim() -> None:
    """v1.1 calls out the exact-match requirement (Week 7 saw "skills" vs
    "skill_tags" mismatches in pre-v1.0 dry runs)."""
    p = build_prompt("...")
    assert "verbatim" in p.lower()


def test_build_prompt_mentions_course_schema_constraints() -> None:
    p = build_prompt("...")
    assert "Course schema" in p
    assert "evidence_snippet" in p
    assert "schema_version" in p


def test_build_prompt_disallows_markdown_fences() -> None:
    p = build_prompt("...")
    assert "no markdown fences" in p.lower()


def test_build_prompt_explains_confidence_rubric() -> None:
    p = build_prompt("...")
    assert "0.95" in p
    assert "0.70" in p


def test_build_prompt_specifies_course_code_format() -> None:
    p = build_prompt("...")
    assert "AAI 6600" in p or "CS 5800" in p


def test_review_enrichment_uses_v1_1() -> None:
    """The enrichment pipeline must pull v1.1, not the old v1.0 prompt.
    Guard against accidental import revert."""
    from llm import review_enrichment
    # build_prompt is re-exported from whichever version is wired
    assert review_enrichment.build_prompt is build_prompt
