"""Syllabus PDF parser using PyMuPDF (fitz).

Output is intentionally **best-effort and minimal** — different syllabi
have wildly different formats (some have explicit "Course Code: AAI 6600"
banners, others bury it in a header table). We extract:
  - full raw text (line-broken, no formatting)
  - cheap regex guesses for course_code / term / credits / instructor name

The LLM step (Week 3 llm/extract_v1) is the **canonical** structured
extractor that produces a Course. SyllabusExtraction is a pre-LLM
artifact: feed `raw_text` to the LLM, use the guesses as fallback /
sanity check.

PII note: the extractor does NOT redact emails. Faculty emails in syllabi
are publicly distributed; redaction is the caller's choice. Don't pipe
SyllabusExtraction.raw_text into Co-op contexts where student PII matters.
"""

from __future__ import annotations

import re
from pathlib import Path

import fitz  # PyMuPDF
from pydantic import BaseModel, ConfigDict, Field

from scrapers._base import logger

# Same pattern as schemas/course.py COURSE_CODE_PATTERN, but with anchors removed
# so we can search inside arbitrary text. Department codes are 2-4 uppercase
# letters, course numbers are 4 digits with optional trailing letter.
_COURSE_CODE_RE = re.compile(r"\b([A-Z]{2,4})\s?(\d{4}[A-Z]?)\b")

# Common term formats: "Spring 2026", "Fall 2025", "Summer I 2026", "Spring/Fall TBD"
_TERM_RE = re.compile(
    r"\b(Spring|Summer(?:\s+[I]{1,2})?|Fall|Winter)\s+(\d{4})\b",
    re.IGNORECASE,
)

# "Credit hours: 3" / "Credits: 4" / "3 credits"
# \b on the trailing \d guards against matching trailing digits inside year
# numbers — "Spring 2026\nCredit hours: 3" would otherwise match "26\nCredit"
# via the second alternative and report credits=26.
_CREDITS_RE = re.compile(
    r"(?:Credit\s+hours?|Credits?)\s*[:=]?\s*(\d{1,2})\b"
    r"|\b(\d{1,2})\s+credits?\b",
    re.IGNORECASE,
)

# "Instructor: Dr. Hema Seshadri" / "Full name: Dr. Hema Seshadri"
_INSTRUCTOR_RE = re.compile(
    r"(?:Instructor|Full\s+name|Professor)\s*[:=]\s*([A-Z][A-Za-z.\-']+(?:\s+[A-Z][A-Za-z.\-']+)+)",
)


class SyllabusExtraction(BaseModel):
    """Pre-LLM extraction from a syllabus PDF.

    Caller passes `raw_text` to LLM extraction (Week 3) for the canonical
    structured Course. Guess fields are for sanity-checking the LLM output:
    if LLM says CS 5800 but the syllabus says AAI 6600, something is wrong.
    """

    model_config = ConfigDict(extra="forbid")

    raw_text: str = Field(min_length=1, description="Full PDF text, page-broken by '\\n'")
    page_count: int = Field(ge=1)
    estimated_course_code: str | None = None
    estimated_term: str | None = None
    estimated_credits: int | None = None
    estimated_instructor_name: str | None = None


def extract_text(pdf_path: str | Path) -> tuple[str, int]:
    """Extract all text from a PDF. Returns (text, page_count)."""
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")

    doc = fitz.open(str(path))
    try:
        text = "\n".join(page.get_text() for page in doc)
        return text, doc.page_count
    finally:
        doc.close()


def parse_syllabus(pdf_path: str | Path) -> SyllabusExtraction:
    """Parse a syllabus PDF into raw_text + best-effort guesses.

    Never raises on parse errors — if a guess regex doesn't match, the field
    stays None. The only exception is FileNotFoundError if the PDF is missing.
    """
    text, page_count = extract_text(pdf_path)

    extraction = SyllabusExtraction(
        raw_text=text,
        page_count=page_count,
        estimated_course_code=_guess_course_code(text),
        estimated_term=_guess_term(text),
        estimated_credits=_guess_credits(text),
        estimated_instructor_name=_guess_instructor(text),
    )

    logger.info(
        "syllabus_parsed",
        path=str(pdf_path),
        page_count=page_count,
        text_chars=len(text),
        guessed_code=extraction.estimated_course_code,
        guessed_term=extraction.estimated_term,
    )
    return extraction


# === Guessers (private) ============================================

def _guess_course_code(text: str) -> str | None:
    """First plausible course code in the first ~2000 chars (header area)."""
    head = text[:2000]
    match = _COURSE_CODE_RE.search(head)
    return f"{match.group(1)} {match.group(2)}" if match else None


def _guess_term(text: str) -> str | None:
    head = text[:2000]
    match = _TERM_RE.search(head)
    if not match:
        return None
    season = match.group(1).strip().title()
    year = match.group(2)
    return f"{season} {year}"


def _guess_credits(text: str) -> int | None:
    head = text[:2000]
    match = _CREDITS_RE.search(head)
    if not match:
        return None
    raw = match.group(1) or match.group(2)
    try:
        n = int(raw)
        # Sanity: reject obvious non-credit numbers (4 digits = year, not credits)
        return n if 0 <= n <= 12 else None
    except (TypeError, ValueError):
        return None


def _guess_instructor(text: str) -> str | None:
    head = text[:2000]
    match = _INSTRUCTOR_RE.search(head)
    return match.group(1).strip() if match else None


__all__ = [
    "SyllabusExtraction",
    "extract_text",
    "parse_syllabus",
]
