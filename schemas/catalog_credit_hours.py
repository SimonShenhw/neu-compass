"""Literal catalog hours, not selected section credits or degree-counting rules.

中文：保留精确小数和范围；不取端点/平均数写入旧整数 credits 字段。
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

NUMBER = r"(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)"
HOURS_RE = re.compile(rf"(?P<minimum>{NUMBER})(?:\s*[-–—]\s*(?P<maximum>{NUMBER}))?\s*Hours?")


def literal_bounds(text: str) -> tuple[str, Decimal, Decimal]:
    if not text or len(text) > 100 or text != " ".join(text.split()):
        raise ValueError("Catalog hours must be nonblank, normalized and bounded")
    match = HOURS_RE.fullmatch(text)
    if match is None:
        raise ValueError("Unsupported catalog hours; do not guess a fixed credit")
    minimum = Decimal(match["minimum"])
    maximum = Decimal(match["maximum"]) if match["maximum"] is not None else minimum
    if not 0 <= minimum <= maximum <= 12:
        raise ValueError("Hours outside existing 0-12 budget or reversed range")
    return ("range" if match["maximum"] is not None else "fixed"), minimum, maximum


class CatalogCreditHours(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format_version: Literal["1"] = "1"
    raw_text: str = Field(min_length=1, max_length=100)
    kind: Literal["fixed", "range"]
    minimum: Decimal = Field(ge=0, le=12)
    maximum: Decimal = Field(ge=0, le=12)

    @model_validator(mode="after")
    def consistent_literal(self):
        if (self.kind, self.minimum, self.maximum) != literal_bounds(self.raw_text):
            raise ValueError("Hours kind/bounds do not match the recorded literal")
        return self

    @classmethod
    def from_text(cls, text: str) -> CatalogCreditHours:
        kind, minimum, maximum = literal_bounds(text)
        return cls(raw_text=text, kind=kind, minimum=minimum, maximum=maximum)

    def fixed_integer(self) -> int | None:
        if self.kind == "fixed" and self.minimum == self.minimum.to_integral_value():
            return int(self.minimum)
        return None
