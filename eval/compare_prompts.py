"""Compare two Course extractions field-by-field.

Use case: when iterating on extract_v1 -> extract_v2, run both prompts on
the same source materials, then diff the resulting JSON against Ground
Truth (or against each other) to see where they disagree.

This module deliberately does NOT call Gemini. Caller produces two
Course JSONs (real LLM run, fixture, manual edit, whatever) and passes
them in. Decouples eval logic from API costs.

CLI:
    python eval/compare_prompts.py path/to/a.json path/to/b.json
    python eval/compare_prompts.py a.json b.json --reference data/ground_truth/aai_6600.json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from schemas.course import Course  # noqa: E402

# Fields not worth diffing — they always differ between runs / are auto-set.
IGNORE_FIELDS: frozenset[str] = frozenset({"created_at", "updated_at"})


@dataclass
class FieldDiff:
    """One field's comparison result."""

    field_name: str
    a_value: Any
    b_value: Any
    equal: bool
    a_matches_reference: bool | None = None
    b_matches_reference: bool | None = None


@dataclass
class ComparisonReport:
    """Summary of comparing two Course extractions."""

    diffs: list[FieldDiff] = field(default_factory=list)
    fields_compared: int = 0
    fields_equal: int = 0
    a_reference_score: float | None = None  # frac of fields matching reference
    b_reference_score: float | None = None

    @property
    def agreement_rate(self) -> float:
        return self.fields_equal / self.fields_compared if self.fields_compared else 0.0


def diff_courses(
    a: Course,
    b: Course,
    *,
    reference: Course | None = None,
) -> ComparisonReport:
    """Compare two Course instances. If reference given, also score each
    against it for ground-truth-aware A/B."""
    report = ComparisonReport()

    a_dump = a.model_dump()
    b_dump = b.model_dump()
    ref_dump = reference.model_dump() if reference else None

    for fname in sorted(set(a_dump) | set(b_dump)):
        if fname in IGNORE_FIELDS:
            continue

        a_val = a_dump.get(fname)
        b_val = b_dump.get(fname)
        equal = _values_equal(a_val, b_val)

        a_match = b_match = None
        if ref_dump is not None:
            ref_val = ref_dump.get(fname)
            a_match = _values_equal(a_val, ref_val)
            b_match = _values_equal(b_val, ref_val)

        report.diffs.append(FieldDiff(
            field_name=fname,
            a_value=a_val, b_value=b_val,
            equal=equal,
            a_matches_reference=a_match,
            b_matches_reference=b_match,
        ))
        report.fields_compared += 1
        if equal:
            report.fields_equal += 1

    if ref_dump is not None:
        scored = [d for d in report.diffs if d.a_matches_reference is not None]
        if scored:
            report.a_reference_score = sum(1 for d in scored if d.a_matches_reference) / len(scored)
            report.b_reference_score = sum(1 for d in scored if d.b_matches_reference) / len(scored)

    return report


def _values_equal(a: Any, b: Any) -> bool:
    """Value equality with list-as-set semantics for unordered list fields.

    Pydantic dumps lists in order, but topics_covered / skill_tags etc.
    are conceptually sets — order shouldn't count. evidence_snippets is
    structural data so we keep order there.
    """
    if isinstance(a, list) and isinstance(b, list):
        # heuristic: lists of strings are treated as sets for diff purposes
        if all(isinstance(x, str) for x in a) and all(isinstance(x, str) for x in b):
            return sorted(a) == sorted(b)
    return a == b


def render_text_report(report: ComparisonReport) -> str:
    """Human-readable summary. Suitable for stdout / CI artifact."""
    lines = [
        "=" * 60,
        f"Field agreement: {report.fields_equal}/{report.fields_compared} "
        f"({report.agreement_rate:.0%})",
    ]
    if report.a_reference_score is not None:
        lines.append(
            f"vs reference:    A={report.a_reference_score:.0%}  "
            f"B={report.b_reference_score:.0%}"
        )
    lines.append("=" * 60)

    diffs_only = [d for d in report.diffs if not d.equal]
    if not diffs_only:
        lines.append("No field differences.")
        return "\n".join(lines)

    lines.append(f"\n{len(diffs_only)} differing field(s):\n")
    for d in diffs_only:
        lines.append(f"  · {d.field_name}")
        lines.append(f"      A: {_short(d.a_value)}")
        lines.append(f"      B: {_short(d.b_value)}")
        if d.a_matches_reference is not None:
            tag_a = "✓" if d.a_matches_reference else "✗"
            tag_b = "✓" if d.b_matches_reference else "✗"
            lines.append(f"      reference: A {tag_a}  B {tag_b}")
    return "\n".join(lines)


def _short(value: Any, max_len: int = 80) -> str:
    s = json.dumps(value, ensure_ascii=False, default=str)
    return s if len(s) <= max_len else s[: max_len - 1] + "…"


def cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("a", type=Path, help="Course JSON dump A")
    parser.add_argument("b", type=Path, help="Course JSON dump B")
    parser.add_argument(
        "--reference", type=Path, default=None,
        help="Optional Ground Truth JSON to score A and B against",
    )
    args = parser.parse_args()

    a = Course.model_validate_json(args.a.read_text(encoding="utf-8"))
    b = Course.model_validate_json(args.b.read_text(encoding="utf-8"))
    ref = (
        Course.model_validate_json(args.reference.read_text(encoding="utf-8"))
        if args.reference else None
    )

    report = diff_courses(a, b, reference=ref)
    print(render_text_report(report))
    return 0


if __name__ == "__main__":
    sys.exit(cli())


__all__ = [
    "IGNORE_FIELDS",
    "ComparisonReport",
    "FieldDiff",
    "diff_courses",
    "render_text_report",
]
