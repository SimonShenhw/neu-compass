"""Tests for scrapers.syllabus — PyMuPDF text extraction + heuristic guessers."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from scrapers.syllabus import (
    SyllabusExtraction,
    extract_text,
    parse_syllabus,
)


def _make_pdf(tmp_path: Path, lines: list[str], filename: str = "test.pdf") -> Path:
    """Build a minimal PDF with given lines, one per insert. Returns path."""
    doc = fitz.open()
    page = doc.new_page()
    y = 50
    for line in lines:
        page.insert_text((50, y), line)
        y += 20
    pdf_path = tmp_path / filename
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


# === extract_text ===

def test_extract_text_returns_content_and_pagecount(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path, ["Hello, syllabus!"])
    text, pages = extract_text(pdf)
    assert "Hello, syllabus!" in text
    assert pages == 1


def test_extract_text_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        extract_text(tmp_path / "no_such.pdf")


def test_extract_text_handles_multipage(tmp_path: Path) -> None:
    doc = fitz.open()
    for i in range(3):
        page = doc.new_page()
        page.insert_text((50, 50), f"Page {i+1} content")
    pdf_path = tmp_path / "multi.pdf"
    doc.save(str(pdf_path))
    doc.close()

    text, pages = extract_text(pdf_path)
    assert pages == 3
    assert "Page 1 content" in text
    assert "Page 3 content" in text


# === parse_syllabus full path ===

def test_parse_syllabus_returns_extraction(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path, [
        "Course title: Applied Artificial Intelligence",
        "Course number: AAI 6600",
        "Term and year: Spring 2026",
        "Credit hours: 3",
        "Instructor: Dr. Hema Seshadri",
    ])
    extraction = parse_syllabus(pdf)
    assert isinstance(extraction, SyllabusExtraction)
    assert extraction.page_count == 1
    assert "AAI 6600" in extraction.raw_text


def test_parse_syllabus_guesses_course_code_aai(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path, ["Course number (CRN): AAI6600"])
    extraction = parse_syllabus(pdf)
    # Regex normalizes "AAI6600" -> "AAI 6600"
    assert extraction.estimated_course_code == "AAI 6600"


def test_parse_syllabus_guesses_course_code_with_letter(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path, ["Course code: DS 5230A spring offering"])
    assert parse_syllabus(pdf).estimated_course_code == "DS 5230A"


def test_parse_syllabus_term_spring(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path, ["Term and year: Spring 2026"])
    assert parse_syllabus(pdf).estimated_term == "Spring 2026"


def test_parse_syllabus_term_fall(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path, ["Offered Fall 2025"])
    assert parse_syllabus(pdf).estimated_term == "Fall 2025"


def test_parse_syllabus_credits(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path, ["Credit hours: 3"])
    assert parse_syllabus(pdf).estimated_credits == 3


def test_parse_syllabus_credits_alt_format(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path, ["This is a 4 credits course"])
    assert parse_syllabus(pdf).estimated_credits == 4


def test_parse_syllabus_credits_rejects_implausible(tmp_path: Path) -> None:
    """4-digit number near the credits keyword shouldn't be mistaken for credits."""
    pdf = _make_pdf(tmp_path, ["Credit hours: 99"])
    # 99 is technically matched but out of [0,12] sanity range -> None
    assert parse_syllabus(pdf).estimated_credits is None


def test_parse_syllabus_instructor(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path, ["Full name: Dr. Hema Seshadri"])
    assert parse_syllabus(pdf).estimated_instructor_name == "Dr. Hema Seshadri"


def test_parse_syllabus_instructor_keyword_alt(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path, ["Instructor: Prof. John Wilder"])
    assert parse_syllabus(pdf).estimated_instructor_name == "Prof. John Wilder"


def test_parse_syllabus_handles_no_matches(tmp_path: Path) -> None:
    """Empty / unstructured PDF shouldn't crash; all guesses None."""
    pdf = _make_pdf(tmp_path, ["This is just prose with no metadata blocks."])
    extraction = parse_syllabus(pdf)
    assert extraction.estimated_course_code is None
    assert extraction.estimated_term is None
    assert extraction.estimated_credits is None
    assert extraction.estimated_instructor_name is None


def test_parse_syllabus_full_aai6600_fixture(tmp_path: Path) -> None:
    """All four guessers fire on the realistic AAI 6600 header block."""
    pdf = _make_pdf(tmp_path, [
        "Course title: Applied Artificial Intelligence",
        "Course number (CRN): AAI6600",
        "Term and year: Spring 2026",
        "Credit hours: 3",
        "Course format: Hybrid",
        "Full name: Dr. Hema Seshadri",
    ])
    e = parse_syllabus(pdf)
    assert e.estimated_course_code == "AAI 6600"
    assert e.estimated_term == "Spring 2026"
    assert e.estimated_credits == 3
    assert e.estimated_instructor_name == "Dr. Hema Seshadri"


# === SyllabusExtraction Pydantic constraints ===

def test_extraction_rejects_empty_raw_text() -> None:
    with pytest.raises(ValueError):
        SyllabusExtraction(raw_text="", page_count=1)


def test_extraction_rejects_zero_pages() -> None:
    with pytest.raises(ValueError):
        SyllabusExtraction(raw_text="x", page_count=0)


def test_extraction_extra_forbidden() -> None:
    with pytest.raises(ValueError):
        SyllabusExtraction(raw_text="x", page_count=1, unknown="x")
