"""NEU Course Catalog scraper.

Fetches official course descriptions from catalog.northeastern.edu and
normalizes them to a CatalogEntry. Used as the L1 hard-fields source for
courses (PLAN §1.4 — official Catalog feeds the alias system L1 layer).

== STATUS: SCAFFOLD ==

The interface (CatalogEntry + fetch_course) is stable and tested via
mocked httpx responses. The actual URL pattern + HTML parsing is marked
TODO — needs live exploration of NEU's catalog structure (CPS courses
appear at https://catalog.northeastern.edu/course-descriptions/<slug>/
but the slug strategy and HTML structure vary by year).

When live impl lands, the function signature below should not change —
only the body. Tests should switch from mocked HTML fixtures to recorded
real responses (vcrpy or similar) so we can verify the parser against
actual catalog output.
"""

from __future__ import annotations

import httpx
from pydantic import BaseModel, ConfigDict, Field

from scrapers._base import create_client, fetch_with_retry, logger

CATALOG_BASE_URL = "https://catalog.northeastern.edu"


class CatalogEntry(BaseModel):
    """Normalized output of the NEU catalog scraper.

    Fields map directly to schemas.course.Course L1 hard fields where possible.
    description is kept as raw_text candidate for the embedder (Week 4).
    cross_listed_codes feeds course_aliases L1 entries automatically.
    """

    model_config = ConfigDict(extra="forbid")

    course_code: str = Field(description="Canonical, e.g. 'AAI 6600'")
    course_name: str
    description: str | None = None
    credits: int | None = Field(default=None, ge=0, le=12)
    prereqs: list[str] = Field(default_factory=list)
    cross_listed_codes: list[str] = Field(default_factory=list)
    catalog_url: str | None = None


def fetch_course(
    course_code: str,
    *,
    client: httpx.Client | None = None,
) -> CatalogEntry:
    """Fetch one course from NEU catalog by code (e.g. 'AAI 6600').

    TODO(Week 2 live impl):
      1. Resolve course_code -> catalog URL. NEU CPS path looks like
         /course-descriptions/<dept-slug>/ followed by an in-page anchor.
         Need to either (a) cache the dept index page once and grep for
         the course code, or (b) construct slug if the URL pattern is
         deterministic. Probe a few endpoints first.
      2. Parse HTML with beautifulsoup4. Look for:
           - Title block (course code + name)
           - Description paragraph
           - "X.000 Credits" or "(0-3 hours)" credit indicator
           - "Prerequisite(s):" line
           - Cross-listed marker (often "(Cross-listed with XYZ 1234)")
      3. Normalize prereqs: split on commas, drop "or" / "and" connectors,
         apply COURSE_CODE_PATTERN regex to keep only valid codes.
      4. Return CatalogEntry. Don't write to DB here — caller decides.

    Caller should pass an httpx.Client they manage; if None, we create one
    just for this call. Per-call client creation is fine for one-off probing
    but inefficient for batch (use the explicit client form).
    """
    raise NotImplementedError(
        "scrapers.neu_catalog.fetch_course: live HTTP impl pending. "
        "See module docstring TODO. Mock via httpx_mock in tests."
    )


def _parse_catalog_html(html: str, course_code: str, source_url: str) -> CatalogEntry:
    """Parse one course's HTML block into CatalogEntry. Pure function; no I/O.

    Separated from fetch_course so tests can feed canned HTML directly.

    TODO(Week 2 live impl): implement once a real catalog HTML sample is
    captured. The shape of CatalogEntry returned must match what
    fetch_course's tests expect.
    """
    raise NotImplementedError("scrapers.neu_catalog._parse_catalog_html: pending")


__all__ = [
    "CATALOG_BASE_URL",
    "CatalogEntry",
    "fetch_course",
]
