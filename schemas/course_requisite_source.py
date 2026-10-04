"""Official department input identity, distinct from program/campus scope."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_BYTES = 2_000_000


class CourseRequisiteSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format_version: int = Field(default=1, ge=1, le=1)
    url: str
    catalog_year: str
    captured_at: datetime
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_count: int = Field(gt=0, le=MAX_BYTES)
    page_title: str = Field(min_length=1, max_length=300)

    @field_validator("url")
    @classmethod
    def official_url(cls, value):
        if not re.fullmatch(r"https://catalog\.northeastern\.edu/course-descriptions/[a-z]{2,8}/", value):
            raise ValueError("Exact official course department URL required")
        return value

    @field_validator("catalog_year")
    @classmethod
    def edition(cls, value):
        if not re.fullmatch(r"\d{4}-\d{4}", value) or int(value[5:]) != int(value[:4]) + 1:
            raise ValueError("Consecutive catalog edition required")
        return value

    @field_validator("captured_at")
    @classmethod
    def aware_time(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Capture timestamp must be timezone-aware")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def subject_heading(self):
        if not self.page_title.endswith(f"({self.url.rstrip('/').split('/')[-1].upper()})"):
            raise ValueError("Heading does not match source department")
        return self


def inspect_course_html(content: bytes, *, url: str, catalog_year: str) -> str:
    if not content or len(content) > MAX_BYTES:
        raise ValueError("Course HTML outside size budget")
    soup = BeautifulSoup(content, "html.parser", from_encoding="utf-8")
    heading = soup.find("h1")
    if heading is None:
        raise ValueError("Missing department heading")
    title = " ".join(heading.get_text(" ", strip=True).split())
    edition = re.search(r"(\d{4}-\d{4})\s+Edition", soup.get_text(" ", strip=True))
    if not edition or edition.group(1) != catalog_year:
        raise ValueError("Course page edition mismatch")
    # Reuse field and cross-field checks before writing any archive bytes.
    CourseRequisiteSource(url=url, catalog_year=catalog_year, page_title=title,
        captured_at=datetime.now(timezone.utc), sha256=hashlib.sha256(content).hexdigest(), byte_count=len(content))
    if not soup.select("div.courseblock"):
        raise ValueError("Missing course blocks")
    return title


def verify_course_source(metadata: CourseRequisiteSource, source_dir: Path) -> bytes:
    stem = source_dir / metadata.sha256
    html, sidecar = stem.with_suffix(".html"), stem.with_suffix(".json")
    if html.stat().st_size > MAX_BYTES or sidecar.stat().st_size > 16_000:
        raise ValueError("Archive outside size budget")
    content = html.read_bytes()
    archived = CourseRequisiteSource.model_validate_json(sidecar.read_text(encoding="utf-8"))
    if (archived != metadata or hashlib.sha256(content).hexdigest() != metadata.sha256
            or len(content) != metadata.byte_count):
        raise ValueError("Course source content/metadata mismatch")
    if inspect_course_html(content, url=metadata.url, catalog_year=metadata.catalog_year) != metadata.page_title:
        raise ValueError("Course source heading mismatch")
    return content
