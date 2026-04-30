"""Tests for llm.prompts.extract_v1 — pure template, no LLM calls."""

from __future__ import annotations

from llm.formatter import SourceDocument, format_sources
from llm.prompts.extract_v1 import (
    PROMPT_TEMPLATE,
    PROMPT_VERSION,
    build_prompt,
)


def test_prompt_version_is_semver() -> None:
    parts = PROMPT_VERSION.split(".")
    assert len(parts) >= 2
    assert all(p.isdigit() for p in parts)


def test_build_prompt_substitutes_sources() -> None:
    sources_xml = format_sources([
        SourceDocument(source_id="syl", source_type="syllabus", content="AAI 6600"),
    ])
    result = build_prompt(sources_xml)
    assert "AAI 6600" in result
    assert sources_xml in result


def test_build_prompt_mentions_course_schema_constraints() -> None:
    """Sanity that the prompt actually instructs the LLM about Course rules."""
    p = build_prompt("...")
    assert "Course schema" in p
    assert "evidence_snippet" in p
    assert "schema_version" in p


def test_build_prompt_disallows_markdown_fences() -> None:
    """Common LLM failure mode: wrapping JSON in ```json fences."""
    p = build_prompt("...")
    assert "no markdown fences" in p.lower()


def test_build_prompt_explains_confidence_rubric() -> None:
    p = build_prompt("...")
    # Confidence anchors: 0.95+, 0.85-0.95, 0.70-0.85, <0.70
    assert "0.95" in p
    assert "0.70" in p


def test_build_prompt_specifies_course_code_format() -> None:
    p = build_prompt("...")
    assert "AAI 6600" in p or "CS 5800" in p  # canonical example present


def test_template_uses_sources_placeholder() -> None:
    assert "{sources}" in PROMPT_TEMPLATE
