"""A byte-addressed input archive; hash consistency is not source authenticity."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict, Field, field_validator

from schemas.program_plan import ProgramPlan

MAX_HTML_BYTES = 2_000_000


class SourceCapture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format_version: int = Field(default=1, ge=1, le=1)
    url: str
    catalog_year: str
    captured_at: datetime
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_count: int = Field(gt=0, le=MAX_HTML_BYTES)
    page_title: str = Field(min_length=1, max_length=300)

    @field_validator("url")
    @classmethod
    def official_url(cls, value):
        return ProgramPlan.catalog_origin(value)

    @field_validator("catalog_year")
    @classmethod
    def edition(cls, value):
        if not re.fullmatch(r"\d{4}-\d{4}", value):
            raise ValueError("Invalid edition")
        return ProgramPlan.consecutive_years(value)

    @field_validator("captured_at")
    @classmethod
    def aware_capture(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Capture timestamp needs a timezone")
        return value.astimezone(timezone.utc)


def inspect_html(content: bytes, plan: ProgramPlan) -> str:
    if not content or len(content) > MAX_HTML_BYTES:
        raise ValueError("Source HTML outside size budget")
    soup = BeautifulSoup(content, "html.parser", from_encoding="utf-8")
    title = soup.find("h1")
    if title is None:
        raise ValueError("Missing catalog program heading")
    page_title = title.get_text(" ", strip=True)
    expected_title = plan.source_title.removesuffix(f", {plan.catalog_year} Edition")
    if page_title != expected_title:
        raise ValueError("Catalog page identity mismatch")
    edition = re.search(r"(\d{4}-\d{4})\s+Edition", soup.get_text(" ", strip=True))
    if not edition or edition.group(1) != plan.source_catalog_year:
        raise ValueError("Catalog page edition mismatch")
    return page_title


def verify_archived_source(plan: ProgramPlan, source_dir: Path) -> SourceCapture:
    if not plan.source_html_sha256:
        raise ValueError("Plan has no source byte fingerprint")
    stem = source_dir / plan.source_html_sha256
    html_path, metadata_path = stem.with_suffix(".html"), stem.with_suffix(".json")
    if html_path.stat().st_size > MAX_HTML_BYTES or metadata_path.stat().st_size > 16_000:
        raise ValueError("Source archive outside size budget")
    content = html_path.read_bytes()
    metadata = SourceCapture.model_validate_json(metadata_path.read_text(encoding="utf-8"))
    if (hashlib.sha256(content).hexdigest() != plan.source_html_sha256
            or metadata.sha256 != plan.source_html_sha256 or metadata.byte_count != len(content)
            or metadata.url != plan.source_url or metadata.catalog_year != plan.source_catalog_year
            or metadata.captured_at.date() != plan.captured_on):
        raise ValueError("Source archive metadata/content mismatch")
    if inspect_html(content, plan) != metadata.page_title:
        raise ValueError("Source archive title mismatch")
    return metadata
