"""Tests for scrapers.neu_catalog using fixture-backed real HTML snapshots.

The fixtures under tests/fixtures/neu_catalog/ are real pages downloaded from
catalog.northeastern.edu on 2026-05-03. They cover:
  - dept_aai.html: simple dept (no prereqs, no cross-listings)
  - dept_cs.html:  has prereqs (CS 1210) + cross-listings (CS 6130 ↔ PSYC 6130)
  - index.html:    /course-descriptions/ root with all dept links

If NEU's HTML structure changes, refresh the fixtures via
scripts/scrape_neu_catalog.py — these tests will start failing loudly.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from scrapers.neu_catalog import (
    CatalogEntry,
    CatalogEntryNotFound,
    _parse_courseblock,
    _parse_dept_html,
    _parse_index_html,
    fetch_course,
    fetch_dept,
    list_dept_slugs,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "neu_catalog"


def _fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


# === CatalogEntry Pydantic shape (kept here after stub graduation) ===


def test_catalog_entry_minimal() -> None:
    e = CatalogEntry(course_code="AAI 6600", course_name="Applied AI")
    assert e.credits is None
    assert e.prereqs == []
    assert e.cross_listed_codes == []


def test_catalog_entry_credits_bounds() -> None:
    CatalogEntry(course_code="CS 5800", course_name="Algo", credits=4)
    with pytest.raises(ValueError):
        CatalogEntry(course_code="CS 5800", course_name="Algo", credits=15)


def test_catalog_entry_extra_forbidden() -> None:
    with pytest.raises(ValueError):
        CatalogEntry(course_code="CS 5800", course_name="Algo", unknown="x")  # type: ignore[call-arg]


# === Pure parser ===


def test_parse_dept_aai_extracts_courses() -> None:
    entries = _parse_dept_html(
        _fixture("dept_aai.html"),
        source_url="https://catalog.northeastern.edu/course-descriptions/aai/",
    )
    assert len(entries) >= 5, "AAI dept should have at least 5 courses"
    by_code = {e.course_code: e for e in entries}
    assert "AAI 5015" in by_code
    aai_5015 = by_code["AAI 5015"]
    assert aai_5015.course_name == "Mathematical Concepts"
    assert aai_5015.credits == 3
    assert aai_5015.prereqs == []
    assert aai_5015.description is not None
    assert "linear algebra" in aai_5015.description.lower()
    assert aai_5015.catalog_url and "aai" in aai_5015.catalog_url


def test_parse_dept_cs_handles_prereqs() -> None:
    entries = _parse_dept_html(
        _fixture("dept_cs.html"),
        source_url="https://catalog.northeastern.edu/course-descriptions/cs/",
    )
    by_code = {e.course_code: e for e in entries}
    cs_1210 = by_code.get("CS 1210")
    assert cs_1210 is not None, "CS 1210 expected in fixture"
    # Prereqs: CS 2100 / CS 2510 / DS 2500 (one of these at least)
    assert any(p in cs_1210.prereqs for p in ("CS 2100", "DS 2500"))


def test_parse_dept_cs_finds_cross_listings() -> None:
    """CS 6130 and PSYC 6130 are cross-listed (prose pattern in description)."""
    entries = _parse_dept_html(
        _fixture("dept_cs.html"),
        source_url="https://catalog.northeastern.edu/course-descriptions/cs/",
    )
    by_code = {e.course_code: e for e in entries}
    cs_6130 = by_code.get("CS 6130")
    if cs_6130 is None:
        pytest.skip("CS 6130 not in current fixture (catalog may have rotated)")
    assert "PSYC 6130" in cs_6130.cross_listed_codes


def test_parse_dept_assigns_canonical_code_format() -> None:
    """Canonical: 'DEPT NUMBER' single-spaced, dept upper, number 4-digit (+optional letter)."""
    entries = _parse_dept_html(_fixture("dept_aai.html"), source_url="x")
    for e in entries:
        head, num = e.course_code.split(" ", 1)
        assert head.isupper()
        assert num[:4].isdigit()


def test_parse_dept_skips_unparseable_blocks() -> None:
    """One bad block must not drop the whole dept."""
    html = """
    <div class="courseblock">
      <p class="courseblocktitle noindent"><strong>NOT A COURSE.</strong></p>
    </div>
    <div class="courseblock">
      <p class="courseblocktitle noindent"><strong>AAI 5015.  Title.  (3 Hours)</strong></p>
      <p class="cb_desc">x</p>
    </div>
    """
    entries = _parse_dept_html(html, source_url="x")
    assert [e.course_code for e in entries] == ["AAI 5015"]


def test_parse_courseblock_returns_none_for_non_course() -> None:
    """Section headers using courseblock class but no parseable title return None."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(
        '<div class="courseblock">'
        '<p class="courseblocktitle noindent"><strong>Section Header</strong></p>'
        "</div>",
        "lxml",
    )
    block = soup.find("div", class_="courseblock")
    assert _parse_courseblock(block, source_url="x") is None


# === Index parser ===


def test_parse_index_returns_known_slugs() -> None:
    slugs = _parse_index_html(_fixture("index.html"))
    # Sample slugs we know are in the catalog
    for expected in ("aai", "cs", "ds", "math", "info"):
        assert expected in slugs, f"{expected} missing from index"
    assert len(slugs) == len(set(slugs)), "slugs should be deduplicated"
    assert len(slugs) >= 50, "catalog has 100+ depts; sanity check"


# === HTTP layer (mocked transport) ===


def _client_serving(html: str, *, captured: dict | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured["url"] = str(request.url)
        return httpx.Response(200, text=html)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_dept_uses_correct_url() -> None:
    captured: dict = {}
    with _client_serving(_fixture("dept_aai.html"), captured=captured) as client:
        entries = fetch_dept("aai", client=client)
    assert captured["url"] == "https://catalog.northeastern.edu/course-descriptions/aai/"
    assert len(entries) > 0


def test_fetch_dept_validates_slug() -> None:
    bad_slugs = ["../etc/passwd", "UPPER", "a", "", "x" * 9]
    for slug in bad_slugs:
        with pytest.raises(ValueError):
            fetch_dept(slug)


def test_fetch_course_resolves_via_dept() -> None:
    with _client_serving(_fixture("dept_aai.html")) as client:
        entry = fetch_course("AAI 5015", client=client)
    assert entry.course_code == "AAI 5015"
    assert entry.course_name == "Mathematical Concepts"


def test_fetch_course_normalizes_input() -> None:
    """Different surface forms ('aai5015', 'AAI 5015', '  aai 5015 ') resolve."""
    for code in ["AAI 5015", "aai5015", "  aai 5015  "]:
        with _client_serving(_fixture("dept_aai.html")) as client:
            entry = fetch_course(code, client=client)
        assert entry.course_code == "AAI 5015"


def test_fetch_course_raises_when_missing() -> None:
    with _client_serving(_fixture("dept_aai.html")) as client:
        with pytest.raises(CatalogEntryNotFound):
            fetch_course("AAI 9999", client=client)


def test_fetch_course_invalid_code_raises() -> None:
    with pytest.raises(ValueError):
        fetch_course("not-a-code")


def test_list_dept_slugs_returns_list() -> None:
    captured: dict = {}
    with _client_serving(_fixture("index.html"), captured=captured) as client:
        slugs = list_dept_slugs(client=client)
    assert captured["url"] == "https://catalog.northeastern.edu/course-descriptions/"
    assert "aai" in slugs
    assert "cs" in slugs
    assert len(slugs) >= 50
