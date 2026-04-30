"""Tests for eval.compare_prompts — Course field-by-field diff."""

from __future__ import annotations

from eval.compare_prompts import (
    IGNORE_FIELDS,
    diff_courses,
    render_text_report,
)
from schemas.course import Course, EvidenceSnippet


def _course(**overrides) -> Course:
    base = {
        "course_id": "u1",
        "primary_code": "CS 5800",
        "primary_name": "Algorithms",
    }
    base.update(overrides)
    return Course(**base)


# === Identity comparisons ===

def test_diff_identical_courses_full_agreement() -> None:
    c = _course(credits=4)
    report = diff_courses(c, c)
    assert report.fields_equal == report.fields_compared
    assert report.agreement_rate == 1.0


def test_diff_ignores_timestamps() -> None:
    """created_at / updated_at differ between any two constructions; the
    comparator must not flag them."""
    a = _course()
    b = _course()
    report = diff_courses(a, b)

    diffed_fields = {d.field_name for d in report.diffs}
    assert "created_at" not in diffed_fields
    assert "updated_at" not in diffed_fields


def test_ignore_fields_set_includes_timestamps() -> None:
    assert "created_at" in IGNORE_FIELDS
    assert "updated_at" in IGNORE_FIELDS


# === Field-level differences ===

def test_diff_detects_credits_change() -> None:
    a = _course(credits=4)
    b = _course(credits=3)
    report = diff_courses(a, b)
    diffed = {d.field_name for d in report.diffs if not d.equal}
    assert "credits" in diffed


def test_diff_detects_term_change() -> None:
    a = _course(term="Spring 2026")
    b = _course(term="Fall 2026")
    report = diff_courses(a, b)
    assert any(d.field_name == "term" and not d.equal for d in report.diffs)


# === List-as-set semantics ===

def test_string_lists_compared_unordered() -> None:
    """topics_covered ordering shouldn't count as a difference."""
    a = _course(topics_covered=["dp", "graphs", "search"])
    b = _course(topics_covered=["search", "dp", "graphs"])
    report = diff_courses(a, b)
    topics_diff = next(d for d in report.diffs if d.field_name == "topics_covered")
    assert topics_diff.equal is True


def test_evidence_snippets_compared_in_order() -> None:
    """Structured list elements are compared by position (not as set)."""
    ev1 = EvidenceSnippet(
        field="skill_tags", value=["python"],
        source_id="syl_1", quote="uses python", confidence=0.9,
    )
    ev2 = EvidenceSnippet(
        field="skill_tags", value=["sql"],
        source_id="syl_2", quote="uses sql", confidence=0.9,
    )
    a = _course(skill_tags=["python", "sql"], evidence_snippets=[ev1, ev2])
    b = _course(skill_tags=["python", "sql"], evidence_snippets=[ev2, ev1])
    report = diff_courses(a, b)
    ev_diff = next(d for d in report.diffs if d.field_name == "evidence_snippets")
    # Different order -> not equal under structural comparison
    assert ev_diff.equal is False


# === Reference scoring ===

def test_reference_score_perfect_a_partial_b() -> None:
    reference = _course(credits=4, term="Spring 2026")
    a = _course(credits=4, term="Spring 2026")              # matches
    b = _course(credits=3, term="Spring 2026")              # credits wrong

    report = diff_courses(a, b, reference=reference)
    assert report.a_reference_score == 1.0
    assert report.b_reference_score is not None
    assert report.b_reference_score < 1.0


def test_reference_scoring_skipped_when_no_reference() -> None:
    a = _course()
    b = _course()
    report = diff_courses(a, b)
    assert report.a_reference_score is None
    assert report.b_reference_score is None


def test_field_diff_carries_reference_match_flags() -> None:
    reference = _course(primary_name="Algorithms", credits=4)
    a = _course(primary_name="Algorithms", credits=4)
    b = _course(primary_name="ALGOS", credits=3)

    report = diff_courses(a, b, reference=reference)
    name_diff = next(d for d in report.diffs if d.field_name == "primary_name")
    credits_diff = next(d for d in report.diffs if d.field_name == "credits")

    assert name_diff.a_matches_reference is True
    assert name_diff.b_matches_reference is False
    assert credits_diff.a_matches_reference is True
    assert credits_diff.b_matches_reference is False


# === Text report ===

def test_text_report_no_diffs_message() -> None:
    a = _course()
    report = diff_courses(a, a)
    out = render_text_report(report)
    assert "No field differences" in out


def test_text_report_lists_diffs() -> None:
    a = _course(credits=4)
    b = _course(credits=3)
    out = render_text_report(diff_courses(a, b))
    assert "credits" in out
    assert "100%" not in out  # must NOT claim full agreement when it's not


def test_text_report_truncates_long_values() -> None:
    long_topics = [f"topic_{i:03d}" for i in range(50)]
    a = _course(topics_covered=long_topics)
    b = _course(topics_covered=[])
    out = render_text_report(diff_courses(a, b))
    # Truncation marker present somewhere (long list won't fit in 80 chars)
    assert "…" in out


def test_text_report_includes_reference_marks_when_provided() -> None:
    reference = _course(credits=4)
    a = _course(credits=4)
    b = _course(credits=3)
    out = render_text_report(diff_courses(a, b, reference=reference))
    assert "reference" in out.lower()
    assert "✓" in out
    assert "✗" in out
