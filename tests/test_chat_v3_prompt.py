"""Unit tests for llm.prompts.chat_v3 — conversational, content-grounded
advisor prompt. Pins the v3-specific contract: history block, course
CONTENT in the candidates block, no-code-number-inference rule, and the
did-you-mean instruction."""

from __future__ import annotations

from llm.prompts.chat_v3 import (
    PROMPT_TEMPLATE,
    PROMPT_VERSION,
    build_prompt,
    format_courses_block,
    format_history_block,
)
from rag.retriever import SearchHit
from schemas.course import Course


def _hit(code: str, name: str, **kwargs) -> SearchHit:
    cid = "c-" + code.lower().replace(" ", "-")
    return SearchHit(
        course=Course(course_id=cid, primary_code=code, primary_name=name, **kwargs),
        score=0.5,
    )


def test_prompt_version_is_3_0() -> None:
    assert PROMPT_VERSION == "3.0"


# === History block (new in v3) ===


def test_history_block_renders_turns() -> None:
    block = format_history_block([
        {"role": "user", "content": "AAI 6620 这门课怎么样？"},
        {"role": "assistant", "content": "AAI 6620 是 Applied NLP..."},
    ])
    assert "Student: AAI 6620 这门课怎么样？" in block
    assert "Advisor: AAI 6620 是 Applied NLP..." in block


def test_history_block_empty_renders_first_message_marker() -> None:
    assert "first message" in format_history_block([])
    assert "first message" in format_history_block(None)


def test_build_prompt_includes_history_and_query() -> None:
    p = build_prompt(
        "这门课作业量大吗？",
        [_hit("AAI 6620", "Applied Natural Language Processing")],
        history=[{"role": "user", "content": "AAI 6620 怎么样"}],
    )
    assert "Student: AAI 6620 怎么样" in p
    assert "这门课作业量大吗？" in p
    assert "AAI 6620 — Applied Natural Language Processing" in p


# === Course content in the candidates block (new in v3) ===


def test_course_block_includes_topics_and_skills() -> None:
    # Soft fields require evidence_snippets (PLAN §2.1 invariant on the
    # Course schema) — provide minimal evidence so validation passes.
    evidence = [
        {
            "field": f, "value": v, "source_id": "rmp_review_1",
            "quote": "q", "confidence": 0.9,
        }
        for f, v in (
            ("workload_hours_per_week", 9.0),
            ("difficulty_score", 3.5),
            ("topics_covered", ["tokenization"]),
            ("skill_tags", ["PyTorch"]),
        )
    ]
    block = format_courses_block([
        _hit(
            "AAI 6620", "Applied NLP",
            topics_covered=["tokenization", "transformers", "NER"],
            skill_tags=["PyTorch", "HuggingFace"],
            workload_hours_per_week=9.0,
            difficulty_score=3.5,
            evidence_snippets=evidence,
        ),
    ])
    assert "topics: tokenization; transformers; NER" in block
    assert "skills: PyTorch; HuggingFace" in block
    assert "workload ~9 h/week" in block
    assert "difficulty 3.5/5" in block


def test_course_block_omits_content_lines_when_absent() -> None:
    block = format_courses_block([_hit("AAI 6640", "Applied Deep Learning")])
    assert "topics:" not in block
    assert "skills:" not in block
    assert "workload" not in block


def test_empty_hits_renders_no_match_marker() -> None:
    assert "no matches" in format_courses_block([]).lower()


# === v3 instruction sentinels ===


def test_template_forbids_code_number_inference() -> None:
    """The live bug this rule kills: '6xxx 级别通常属于中级水平' invented
    from the course number."""
    # (Substring chosen to not span the template's line wrap.)
    assert "from the course NUMBER" in PROMPT_TEMPLATE
    assert "NEVER infer difficulty" in PROMPT_TEMPLATE


def test_template_has_did_you_mean_instruction() -> None:
    assert "2-3 most plausible" in PROMPT_TEMPLATE
    assert "ask the student" in PROMPT_TEMPLATE


def test_template_keeps_v2_grounding_and_prefix_rules() -> None:
    assert "Do NOT invent courses" in PROMPT_TEMPLATE
    assert "FORBIDDEN" in PROMPT_TEMPLATE  # cross-discipline rule survives
