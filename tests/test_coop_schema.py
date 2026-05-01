"""Tests for schemas.coop — Pydantic CoopExperience + k-anonymity helper."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from schemas.coop import CoopExperience, Industry, is_uniquely_identifying


def _coop(**overrides: Any) -> CoopExperience:
    base: dict[str, Any] = {
        "coop_id": "coop-1",
        "company": "State Street",
        "role": "Quant Dev",
    }
    base.update(overrides)
    return CoopExperience(**base)


# === Minimal / defaults ===

def test_minimal_coop() -> None:
    c = _coop()
    assert c.coop_id == "coop-1"
    assert c.is_seed_data is False
    assert c.visibility_level == 0
    assert c.related_courses == []


# === Validation ===

def test_visibility_level_bounds() -> None:
    _coop(visibility_level=0)
    _coop(visibility_level=2)
    with pytest.raises(ValidationError):
        _coop(visibility_level=3)
    with pytest.raises(ValidationError):
        _coop(visibility_level=-1)


def test_duration_bounds() -> None:
    _coop(duration_months=4)
    with pytest.raises(ValidationError):
        _coop(duration_months=0)
    with pytest.raises(ValidationError):
        _coop(duration_months=12)


def test_industry_enum_accepts_string_value() -> None:
    c = _coop(industry="quant_fintech")
    assert c.industry == Industry.QUANT_FINTECH


def test_industry_enum_rejects_unknown() -> None:
    with pytest.raises(ValidationError):
        _coop(industry="space_tourism")


def test_extra_forbidden() -> None:
    with pytest.raises(ValidationError):
        _coop(unexpected="x")


def test_coop_id_min_length() -> None:
    with pytest.raises(ValidationError):
        _coop(coop_id="")


def test_company_role_required() -> None:
    with pytest.raises(ValidationError):
        CoopExperience(coop_id="x", company="", role="x")
    with pytest.raises(ValidationError):
        CoopExperience(coop_id="x", company="x", role="")


def test_interview_summary_max_length() -> None:
    """10 KB ceiling. Reasonable for free-text PII-redacted summaries."""
    too_long = "x" * 11_000
    with pytest.raises(ValidationError):
        _coop(interview_summary=too_long)


# === k-anonymity helper ===

def test_unique_triple_flagged() -> None:
    target = _coop(coop_id="t", company="State Street", role="Quant Dev",
                   coop_term="Summer 2025")
    others = [
        _coop(coop_id="o1", company="Fidelity", role="Quant Dev",
              coop_term="Summer 2025"),
        _coop(coop_id="o2", company="State Street", role="ML Engineer",
              coop_term="Summer 2025"),
    ]
    # target's (State Street, Quant Dev, Summer 2025) doesn't match any other
    assert is_uniquely_identifying(target, [target] + others, k=2) is True


def test_pair_passes_k_anonymity() -> None:
    a = _coop(coop_id="a", company="State Street", role="Quant Dev",
              coop_term="Summer 2025")
    b = _coop(coop_id="b", company="State Street", role="Quant Dev",
              coop_term="Summer 2025")
    # 2 matching rows -> not uniquely identifying at k=2
    assert is_uniquely_identifying(a, [a, b], k=2) is False


def test_k_anonymity_self_counts() -> None:
    """When passing the new row INSIDE corpus, it counts toward k. Correct
    semantics: 'is this row uniquely identifying in the final state after
    insert?'"""
    new = _coop(coop_id="new", company="MFS", role="Data Engineer",
                coop_term="Spring 2026")
    # corpus contains 1 other matching MFS Data Engineer Spring 2026
    other = _coop(coop_id="o", company="MFS", role="Data Engineer",
                  coop_term="Spring 2026")
    # Including self in corpus: 2 matches -> not uniquely identifying
    assert is_uniquely_identifying(new, [new, other], k=2) is False


def test_higher_k_threshold() -> None:
    """At k=3, a triple needing 3+ rows: 2 isn't enough."""
    a = _coop(coop_id="a", company="X", role="Y", coop_term="Z")
    b = _coop(coop_id="b", company="X", role="Y", coop_term="Z")
    assert is_uniquely_identifying(a, [a, b], k=3) is True
    c = _coop(coop_id="c", company="X", role="Y", coop_term="Z")
    assert is_uniquely_identifying(a, [a, b, c], k=3) is False
