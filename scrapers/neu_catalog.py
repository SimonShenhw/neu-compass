"""NEU Course Catalog scraper (live impl per PLAN_v2.0 §4.4 P0).

Fetches `<https://catalog.northeastern.edu/course-descriptions/...>` pages
and parses each `<div class="courseblock">` into a CatalogEntry. Pure
parser is `_parse_dept_html`; HTTP is in `fetch_dept` / `list_dept_slugs` /
`fetch_course`. Tests run off real HTML snapshots in
`tests/fixtures/neu_catalog/`.

URL pattern (probed 2026-05-03):
  - Index:    /course-descriptions/
  - Per dept: /course-descriptions/<slug>/  (e.g. /course-descriptions/aai/)

HTML shape:
  <div class="courseblock">
    <p class="courseblocktitle noindent"><strong>CODE.  Title.  (N Hours)</strong></p>
    <p class="cb_desc">description text...</p>
    <p class="courseblockextra noindent">                    [optional]
        <strong>Prerequisite(s): </strong>
        <a class="bubblelink code">CODE</a> with a minimum grade of X
    </p>
    <br/>
  </div>

Cross-listing: catalog encodes cross-listings as prose inside cb_desc:
"CS 6130 and PSYC 6130 are cross-listed." We surface those via a regex
post-pass in `_parse_courseblock`.

Rate limit: 1 req/sec in the bulk script (scripts/scrape_neu_catalog.py).
fetch_dept() reuses the caller's httpx.Client when given for batch use.
"""

from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup
from bs4.element import Tag
from pydantic import BaseModel, ConfigDict, Field

from scrapers._base import create_client, fetch_with_retry, logger

CATALOG_BASE_URL = "https://catalog.northeastern.edu"

# Title format: "AAI 5015.  Mathematical Concepts.  (3 Hours)"
# Lenient on whitespace + accept fractional credits + plural Hour/Hours.
_TITLE_RE = re.compile(
    r"^([A-Z]{2,4})\s?(\d{4}[A-Z]?)\.\s+(.+?)\.\s+\(([\d.]+)\s*Hours?\)\s*$"
)

# "X and Y are cross-listed" prose pattern (case-insensitive, optional hyphen).
_CROSS_LIST_RE = re.compile(
    r"\b([A-Z]{2,4})\s?(\d{4}[A-Z]?)\s+and\s+([A-Z]{2,4})\s?(\d{4}[A-Z]?)\s+are\s+cross-?listed",
    re.IGNORECASE,
)

# Course code inside <a class="bubblelink code">.
_CODE_ONLY_RE = re.compile(r"^([A-Z]{2,4})\s?(\d{4}[A-Z]?)$")

# Index page link pattern: /course-descriptions/<slug>/
_DEPT_HREF_RE = re.compile(r"^/course-descriptions/([a-z]{2,8})/?$")

# Strict slug shape used by fetch_dept input validation.
_SLUG_RE = re.compile(r"^[a-z]{2,8}$")


class CatalogEntry(BaseModel):
    """Normalized output of the NEU catalog scraper."""

    model_config = ConfigDict(extra="forbid")

    course_code: str = Field(description="Canonical, e.g. 'AAI 6600'")
    course_name: str
    description: str | None = None
    credits: int | None = Field(default=None, ge=0, le=12)
    prereqs: list[str] = Field(default_factory=list)
    cross_listed_codes: list[str] = Field(default_factory=list)
    catalog_url: str | None = None


class CatalogEntryNotFound(LookupError):
    """The dept page parsed but didn't contain the requested course code."""


# === Public HTTP-driven entry points ===


def list_dept_slugs(*, client: httpx.Client | None = None) -> list[str]:
    """Fetch /course-descriptions/ and return all dept slugs (e.g. 'aai').

    Slugs are deduplicated; insertion order matches the catalog's alphabetical
    rendering.
    """
    own_client = client is None
    client = client or create_client()
    try:
        resp = fetch_with_retry(client, f"{CATALOG_BASE_URL}/course-descriptions/")
        return _parse_index_html(resp.text)
    finally:
        if own_client:
            client.close()


def fetch_dept(
    dept_slug: str,
    *,
    client: httpx.Client | None = None,
) -> list[CatalogEntry]:
    """Fetch one /course-descriptions/<slug>/ page; return all courses on it.

    Raises ValueError on bad slug shape (defends against path traversal —
    we interpolate the slug into a URL). Empty list is a legitimate result
    if the catalog page has no `<div class='courseblock'>` blocks.
    """
    # Validate BEFORE lowercasing — uppercase / mixed case is treated as a
    # bug (the catalog only uses lowercase slugs, so anything else likely
    # means the caller passed the wrong token, e.g. a course code).
    raw = dept_slug.strip("/")
    if not _SLUG_RE.match(raw):
        raise ValueError(f"Invalid dept slug: {dept_slug!r}")
    slug = raw

    url = f"{CATALOG_BASE_URL}/course-descriptions/{slug}/"
    own_client = client is None
    client = client or create_client()
    try:
        log = logger.bind(scraper="neu_catalog", dept=slug)
        log.info("fetch_dept.start", url=url)
        resp = fetch_with_retry(client, url)
        entries = _parse_dept_html(resp.text, source_url=url)
        log.info("fetch_dept.done", count=len(entries))
        return entries
    finally:
        if own_client:
            client.close()


def fetch_course(
    course_code: str,
    *,
    client: httpx.Client | None = None,
) -> CatalogEntry:
    """Fetch one course by canonical code.

    Resolves dept slug from the prefix, fetches the dept page, returns the
    matching entry. Raises CatalogEntryNotFound if the dept doesn't list
    this code.
    """
    m = re.match(r"^([A-Z]{2,4})\s?(\d{4}[A-Z]?)$", course_code.strip().upper())
    if not m:
        raise ValueError(f"Invalid course code: {course_code!r}")
    canonical = f"{m.group(1)} {m.group(2)}"
    dept_slug = m.group(1).lower()

    entries = fetch_dept(dept_slug, client=client)
    for e in entries:
        if e.course_code == canonical:
            return e
    raise CatalogEntryNotFound(
        f"{canonical!r} not found in dept {dept_slug!r}"
    )


# === Pure parsers (no I/O) ===


def _parse_index_html(html: str) -> list[str]:
    """Pull dept slugs from the /course-descriptions/ index page."""
    soup = BeautifulSoup(html, "lxml")
    seen: set[str] = set()
    slugs: list[str] = []
    for a in soup.find_all("a", href=True):
        m = _DEPT_HREF_RE.match(a["href"].strip())
        if not m:
            continue
        slug = m.group(1).lower()
        if slug in seen:
            continue
        seen.add(slug)
        slugs.append(slug)
    return slugs


def _parse_dept_html(html: str, *, source_url: str) -> list[CatalogEntry]:
    """Parse a /course-descriptions/<dept>/ page into CatalogEntry list.

    Resilient: per-block parse errors are logged and skipped (so one
    malformed block doesn't drop the whole dept).
    """
    soup = BeautifulSoup(html, "lxml")
    out: list[CatalogEntry] = []
    for block in soup.find_all("div", class_="courseblock"):
        try:
            entry = _parse_courseblock(block, source_url=source_url)
            if entry is not None:
                out.append(entry)
        except Exception as e:  # never let one bad block tank the whole dept
            logger.warning(
                "neu_catalog.parse_block_failed",
                source_url=source_url,
                error=repr(e),
            )
    return out


def _parse_courseblock(block: Tag, *, source_url: str) -> CatalogEntry | None:
    """One <div class='courseblock'> -> CatalogEntry (or None for non-course blocks)."""
    title_p = block.find("p", class_="courseblocktitle")
    if title_p is None:
        return None
    title_text = title_p.get_text(" ", strip=True)
    m = _TITLE_RE.match(title_text)
    if not m:
        # Title doesn't follow the canonical format — could be a section
        # header dressed in the same class, or a TBA-credits placeholder.
        return None
    course_code = f"{m.group(1).upper()} {m.group(2).upper()}"
    course_name = m.group(3).strip()

    credit_str = m.group(4)
    try:
        credit_val = float(credit_str)
        credits = int(credit_val) if credit_val == int(credit_val) else None
    except ValueError:
        credits = None

    desc_p = block.find("p", class_="cb_desc")
    description = desc_p.get_text(" ", strip=True) if desc_p else None

    # Prereqs: <p class="courseblockextra"> with strong "Prerequisite(s)" header.
    prereqs: list[str] = []
    seen_prereqs: set[str] = set()
    for extra in block.find_all("p", class_="courseblockextra"):
        label = extra.find("strong")
        if label is None or "rerequisite" not in label.get_text():
            continue
        for a in extra.find_all("a", class_="bubblelink"):
            text = a.get_text(strip=True)
            cm = _CODE_ONLY_RE.match(text)
            if cm is None:
                continue
            code = f"{cm.group(1)} {cm.group(2)}"
            if code != course_code and code not in seen_prereqs:
                seen_prereqs.add(code)
                prereqs.append(code)

    # Cross-listed: prose pattern inside cb_desc.
    cross_listed: list[str] = []
    seen_cross: set[str] = set()
    if description:
        for cm in _CROSS_LIST_RE.finditer(description):
            for grp_idx in (1, 3):
                code = f"{cm.group(grp_idx).upper()} {cm.group(grp_idx + 1).upper()}"
                if code != course_code and code not in seen_cross:
                    seen_cross.add(code)
                    cross_listed.append(code)

    return CatalogEntry(
        course_code=course_code,
        course_name=course_name,
        description=description,
        credits=credits,
        prereqs=prereqs,
        cross_listed_codes=cross_listed,
        catalog_url=source_url,
    )


__all__ = [
    "CATALOG_BASE_URL",
    "CatalogEntry",
    "CatalogEntryNotFound",
    "fetch_course",
    "fetch_dept",
    "list_dept_slugs",
]
