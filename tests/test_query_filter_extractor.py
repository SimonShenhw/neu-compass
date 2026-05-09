"""Tests for llm.query_filter_extractor — Layer 2 of the v3.0 RAG plan.

Two paths under test:
  1. Pure-regex extraction — fast path, ~80% of real queries.
  2. Adaptive (regex first, LLM fallback) — gates the LLM call on a
     program-keyword presence check, so most no-signal queries skip it.

The LLM hook is faked here; production wires Gemini structured output.
"""

from __future__ import annotations

import pytest

from llm.query_filter_extractor import (
    KNOWN_PROGRAM_PREFIXES,
    extract_filters_adaptive,
    extract_filters_regex,
)
from schemas.query_filter import QueryFilters


# === Regex path ===


@pytest.mark.parametrize(
    "query,expected_prefix",
    [
        ("AAI 专业第一学期推荐", "AAI"),
        ("aai专业第一学期", "AAI"),  # lowercase + no space
        ("我是aai专业，能给我推荐第一个学期的选课嘛？", "AAI"),
        ("CS major requirements", "CS"),
        ("数据科学 DS 第一学期", "DS"),
        ("EECE first semester core", "EECE"),
        ("INFO 系学生方向", "INFO"),
    ],
)
def test_regex_extracts_known_prefix(query: str, expected_prefix: str) -> None:
    result = extract_filters_regex(query)
    assert result.program_prefix == expected_prefix
    assert not result.is_empty()


def test_regex_returns_empty_when_no_prefix() -> None:
    """No known prefix and no program-keyword → empty filter (passthrough)."""
    result = extract_filters_regex("how do I learn neural networks?")
    assert result.program_prefix is None
    assert result.is_empty()
    assert result.sanitized_query == "how do I learn neural networks?"


def test_regex_returns_empty_for_empty_query() -> None:
    assert extract_filters_regex("").is_empty()
    assert extract_filters_regex("   ").is_empty()


def test_regex_strips_matched_prefix_from_sanitized_query() -> None:
    result = extract_filters_regex("AAI 专业第一学期推荐")
    assert result.sanitized_query == "专业第一学期推荐"


def test_regex_collapses_whitespace_after_strip() -> None:
    """When the prefix sits between spaces, removing it should not leave
    a double-space."""
    result = extract_filters_regex("我想学 AAI 入门课程")
    assert "  " not in result.sanitized_query


def test_regex_normalizes_prefix_to_uppercase() -> None:
    """`primary_code LIKE 'X %'` is uppercase in the data — extractor
    normalizes lowercase user input to match."""
    assert extract_filters_regex("aai 课怎么样").program_prefix == "AAI"
    assert extract_filters_regex("Cs intro").program_prefix == "CS"


def test_regex_word_boundary_avoids_false_positives() -> None:
    """'CS' inside 'CSCI' should NOT match (CSCI isn't in the known set);
    word boundary protects against substring matching."""
    # 'graphics' contains no 'CS' as a word, fine.
    result = extract_filters_regex("graphics for AI 课")
    assert result.program_prefix is None


def test_regex_does_not_match_unknown_prefix() -> None:
    """A 3-letter combo that isn't on the known list (e.g. 'ABC') must not
    be returned as a prefix even if it looks like one."""
    result = extract_filters_regex("ABC 专业怎么样")
    assert result.program_prefix is None


# === Chinese-mixed (re.ASCII consistency with query_normalizer) ===


def test_regex_handles_chinese_mixed_query() -> None:
    """Same fix as query_normalizer: Python 3 \\b is Unicode-aware so
    '我是aai' has no boundary between '是' and 'a' without re.ASCII.
    Our regex must use re.ASCII (and the test pins this)."""
    queries = [
        "我是aai专业的学生",
        "我学AAI专业",
        "听说AAI专业不错",
    ]
    for q in queries:
        assert extract_filters_regex(q).program_prefix == "AAI", f"failed: {q!r}"


# === Adaptive path ===


def test_adaptive_skips_llm_when_regex_succeeds() -> None:
    """Regex catches 'AAI' → adaptive returns immediately, llm_fn never called."""
    calls = []

    def boom(_: str) -> dict:
        calls.append(1)
        raise AssertionError("llm_fn should not be called when regex matches")

    result = extract_filters_adaptive("AAI 专业课", llm_fn=boom)
    assert result.program_prefix == "AAI"
    assert calls == []


def test_adaptive_skips_llm_when_no_program_keyword() -> None:
    """Even with llm_fn provided, adaptive skips it when the query has
    neither a regex prefix NOR a 专业/major-style keyword. Saves cost on
    the 'how do I learn ML' style queries."""
    calls = []

    def fake(_: str) -> dict:
        calls.append(1)
        return {"program_prefix": "CS", "sanitized_query": ""}

    result = extract_filters_adaptive(
        "how do I learn neural networks?", llm_fn=fake,
    )
    assert result.program_prefix is None
    assert calls == []


def test_adaptive_calls_llm_when_program_keyword_present_no_prefix() -> None:
    """Query mentions '专业' but no known prefix → LLM gets to map it."""
    calls = []

    def fake(query: str) -> dict:
        calls.append(query)
        return {"program_prefix": "AAI", "sanitized_query": "第一学期推荐"}

    result = extract_filters_adaptive(
        "我是 AI 专业的，第一学期推荐什么", llm_fn=fake,
    )
    assert calls == ["我是 AI 专业的，第一学期推荐什么"]
    assert result.program_prefix == "AAI"
    assert result.sanitized_query == "第一学期推荐"


def test_adaptive_falls_back_when_llm_raises() -> None:
    """LLM errors must NOT take down the request — degrade to passthrough."""
    def boom(_: str) -> dict:
        raise RuntimeError("Gemini upstream 500")

    result = extract_filters_adaptive("我是某某专业 ", llm_fn=boom)
    assert result.is_empty()


def test_adaptive_falls_back_when_llm_returns_invalid_dict() -> None:
    """LLM returns malformed dict (missing required key) → passthrough."""
    def fake(_: str) -> dict:
        return {"unexpected_field": "AAI"}  # missing 'sanitized_query'

    result = extract_filters_adaptive("我是某某专业", llm_fn=fake)
    assert result.is_empty()


# === Schema invariants ===


def test_query_filters_to_hard_filter_omits_none() -> None:
    """to_hard_filter() must omit None fields — the retriever's
    _sqlite_filter treats key presence as 'apply this filter', so we
    can't pass {"primary_code_prefix": None}."""
    f = QueryFilters(sanitized_query="x")
    assert f.to_hard_filter() == {}

    f = QueryFilters(program_prefix="AAI", sanitized_query="x")
    assert f.to_hard_filter() == {"primary_code_prefix": "AAI"}


def test_known_prefixes_set_includes_neu_top_level() -> None:
    """Pin the prefix set so accidental deletes get caught by tests."""
    assert "AAI" in KNOWN_PROGRAM_PREFIXES
    assert "CS" in KNOWN_PROGRAM_PREFIXES
    assert "DS" in KNOWN_PROGRAM_PREFIXES
    assert "EECE" in KNOWN_PROGRAM_PREFIXES
