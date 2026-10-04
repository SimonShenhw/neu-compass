"""Read-only report for explicitly selected courses in fingerprinted inputs.

中文：不访问网络/数据库；未识别的整段原文标为 unparsed，不导入旧边。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from schemas.course_requisite_source import CourseRequisiteSource, verify_course_source  # noqa: E402
from schemas.course import Course  # noqa: E402
from scrapers.neu_catalog import _parse_courseblock  # noqa: E402
from scrapers.course_description_evidence import extract_description_evidence  # noqa: E402


def build_report(manifest_file: Path, source_dir: Path, course_codes: list[str]) -> dict:
    if manifest_file.stat().st_size > 64_000:
        raise ValueError("Manifest exceeds size budget")
    payload = json.loads(manifest_file.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, list) or not payload or len(payload) > 20:
        raise ValueError("Explicit nonempty bounded source manifest required")
    metadata = [CourseRequisiteSource.model_validate(item) for item in payload]
    if len({item.url for item in metadata}) != len(metadata) or len({item.catalog_year for item in metadata}) != 1:
        raise ValueError("Duplicate department or mixed catalog editions")
    if not course_codes or len(course_codes) > 100:
        raise ValueError("Explicit bounded course list required")
    requested = [Course(course_id="validation-only", primary_code=code, primary_name="Validation").primary_code for code in course_codes]
    if len(set(requested)) != len(requested):
        raise ValueError("Duplicate requested course")
    # Validate ALL inputs before producing any report; no partial stdout success.
    contents = [(item, verify_course_source(item, source_dir)) for item in metadata]
    found = {}
    for source, content in contents:
        soup = BeautifulSoup(content, "html.parser", from_encoding="utf-8")
        for block in soup.select("div.courseblock"):
            title = block.find("p", class_="courseblocktitle")
            if title is None:
                continue
            title_text = " ".join(title.get_text(" ", strip=True).split())
            # Only inspect selected blocks; duplicate selected identities fail.
            code = title_text.split(".", 1)[0]
            if code not in requested:
                continue
            entry = _parse_courseblock(block, source_url=source.url)
            if entry is None or entry.course_code in found:
                raise ValueError("Unparseable or duplicate selected course block")
            if entry.course_code.split()[0].lower() != source.url.rstrip("/").split("/")[-1]:
                raise ValueError("Course/source department mismatch")
            warnings = ["course_block_only_not_full_policy_or_eligibility", "campus_and_personal_pathway_not_declared"]
            description = extract_description_evidence(block)
            warnings.append(f"description_{description.status}_not_eligibility_rule")
            if entry.credit_hours.kind == "range":
                warnings.append("catalog_hours_range_not_selected_section_or_degree_credits")
            elif entry.credits is None:
                warnings.append("fractional_hours_not_representable_as_legacy_integer_credits")
            for name in ["prerequisite", "corequisite"]:
                section = getattr(entry.requisites, name)
                if section.status == "not_listed":
                    warnings.append(f"{name}_not_listed_is_not_no_requirement")
                elif section.status == "unparsed":
                    warnings.append(f"{name}_unparsed_no_partial_rule")
            stack = [section.rule for section in [entry.requisites.prerequisite, entry.requisites.corequisite] if section.rule]
            while stack:
                node = stack.pop()
                if node.course_code == entry.course_code:
                    warnings.append("self_reference_preserved_not_auto_corrected")
                stack.extend(node.children)
            found[entry.course_code] = {
                "course_code": entry.course_code, "course_name": entry.course_name,
                "catalog_year": source.catalog_year, "campus": None,
                "source_url": source.url, "source_html_sha256": source.sha256,
                "captured_at": source.captured_at.isoformat(),
                "source": source.model_dump(mode="json"),
                "description_evidence": description.model_dump(mode="json"),
                "credit_hours": entry.credit_hours.model_dump(mode="json"),
                "requisites": entry.requisites.model_dump(mode="json"), "warnings": list(dict.fromkeys(warnings)),
            }
    if any(code not in found for code in requested):
        raise ValueError("Requested course missing from captured department")
    records = [found[code] for code in requested]
    unparsed = sum(section["status"] == "unparsed" for item in records for name, section in item["requisites"].items() if name != "grammar_version")
    return {"records": records, "unparsed_sections": unparsed,
            "limitation": "Clause syntax and description keyword evidence only; no interpreted approval, enrollment, grades, waivers, offering or full-policy evaluation"}


def cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-file", required=True, type=Path)
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--course-code", required=True, action="append")
    args = parser.parse_args()
    try:
        report = build_report(args.manifest_file, args.source_dir, args.course_code)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        # Valid partial reports are visible, but not mistaken for full parse success.
        return 2 if report["unparsed_sections"] else 0
    except (OSError, ValueError) as exc:
        print(f"Offline course requisite report failed ({type(exc).__name__}); no DB or files changed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(cli())
