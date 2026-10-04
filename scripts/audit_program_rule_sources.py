"""Offline cross-check of this curated Boston bundle against frozen tables.

Checks candidate sets and group amounts, NOT complete policies or eligibility.
中文：不访问网络/数据库；未知页面结构失败，不自动猜规则或改 seed。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from schemas.program_plan import ProgramPlan  # noqa: E402
from schemas.program_source import verify_archived_source  # noqa: E402

CODE_RE = re.compile(r"\b([A-Z]{2,4})\s+(\d{4}[A-Z]?)\b")
DS_HEADINGS = {
    "computer-science": "Computer Science Concentration—Khoury College of Computer Sciences",
    "data-design-visualization": "Data Design and Visualization Concentration—College of Arts, Media and Design",
    "engineering-theory-modeling": "Engineering Theory and Modeling Concentration—College of Engineering",
}


def row_codes(text: str) -> list[str]:
    return [f"{subject} {number}" for subject, number in CODE_RE.findall(text)]


def tables_by_heading(content: bytes) -> dict:
    soup = BeautifulSoup(content, "html.parser", from_encoding="utf-8")
    tables = {}
    for table in soup.select("table.sc_courselist"):
        heading = table.find_previous(["h2", "h3"])
        if heading is None:
            raise ValueError("Source course table has no heading")
        name = " ".join(heading.get_text(" ", strip=True).split())
        if name in tables:
            raise ValueError("Ambiguous source heading")
        tables[name] = [" ".join(row.get_text(" ", strip=True).split()) for row in table.select("tr")]
    return tables


def credit_groups(rows: list[str], *, allow_leading_courses: bool = False) -> list[tuple[int, list[str]]]:
    groups = []
    for row in rows:
        if row == "Optional Co-op":
            break
        minimum = re.search(r"Complete (?:the remaining )?(\d+) semester hours", row)
        if minimum:
            groups.append((int(minimum.group(1)), []))
        elif row_codes(row):
            if not groups:
                if allow_leading_courses:
                    continue  # Fixed project/thesis rows precede the elective groups.
                raise ValueError("Unattached selection candidates")
            groups[-1][1].extend(row_codes(row))
    return groups


def subject_pool(rows: list[str]) -> tuple[set, set, set]:
    subjects, codes, exclusions = set(), set(), set()
    for row in rows:
        subject = re.match(r"^([A-Z]{2,4})\b", row)
        if not subject:
            continue
        found = row_codes(row)
        if "except" in row:
            subjects.add(subject.group(1))
            exclusions.update(found)
        elif found:
            codes.update(found)
        else:
            subjects.add(subject.group(1))
    if not (subjects or codes):
        raise ValueError("Empty source candidate set")
    return subjects, codes, exclusions


def assert_equal(actual, expected, context):
    if actual != expected:
        raise ValueError(f"Source/curated mismatch: {context}")


def required_groups(node) -> list[tuple[str, ...]]:
    """Keep main-course/recitation pairs; never accept OR as mandatory AND."""
    if node.kind == "course":
        return [(node.course_code,)]
    if node.kind != "all_of":
        raise ValueError("Expected mandatory course groups")
    groups = []
    for child in node.children:
        if child.kind == "condition":
            continue  # Textual grade/waiver conditions are not evaluated here.
        if child.kind == "course":
            groups.append((child.course_code,))
        elif child.kind == "all_of" and all(leaf.kind == "course" for leaf in child.children):
            groups.append(tuple(leaf.course_code for leaf in child.children))
        else:
            raise ValueError("Required course pair cannot become an alternative/unknown group")
    return groups


def source_required_groups(rows: list[str]) -> list[tuple[str, ...]]:
    # Course titles repeat the main code (e.g. "Lab for INFO 5100"); do not
    # turn that repeated reference into a second copy of the same course.
    return [tuple(dict.fromkeys(row_codes(row))) for row in rows if row_codes(row)]


def audit_plan(plan: ProgramPlan, source_dir: Path) -> dict:
    verify_archived_source(plan, source_dir)
    content = (source_dir / f"{plan.source_html_sha256}.html").read_bytes()
    tables = tables_by_heading(content)
    children = plan.requirements.children
    checks = []
    if plan.program_id == "cs-ms" and plan.pathway in {"standard", "align"}:
        if plan.pathway == "align":
            assert_equal(required_groups(children[0]), source_required_groups(tables["Align Bridge Coursework"]), "CS Align bridge groups")
            assert_equal(required_groups(children[1]), source_required_groups(tables["Core Requirements"]), "CS Align core")
            checks.append("Align bridge main/recitation groups and separate core")
        breadth = next(node for node in children if node.kind == "select" and node.min_areas)
        source_areas, area = {}, None
        rows = tables["Breadth Areas"]
        if not any(re.search(r"(?:Complete|Select) three courses from at least two", row) and row.endswith("12") for row in rows):
            raise ValueError("Missing breadth amount/area rule")
        for row in rows:
            if row in breadth.areas:
                area = row
                source_areas[area] = []
            elif row_codes(row):
                if area is None:
                    raise ValueError("Unattached breadth course")
                source_areas[area].extend(row_codes(row))
        assert_equal(breadth.areas, source_areas, "CS breadth memberships")
        assert_equal((breadth.min_courses, breadth.min_credits, breadth.min_areas), (3, 12, 2), "CS breadth minima")
        elective = next(node for node in children if node.kind == "select" and not node.min_areas)
        groups = credit_groups(tables["Electives"])
        if len(groups) != 1:
            raise ValueError("Unexpected CS elective groups")
        range_rows = [row for row in tables["Electives"] if " to " in row and len(row_codes(row)) == 2]
        assert_equal([(r.start, r.end) for r in elective.course_ranges], [tuple(row_codes(row)) for row in range_rows], "CS intervals")
        endpoints = {code for row in range_rows for code in row_codes(row)}
        assert_equal(set(elective.course_codes), set(groups[0][1]) - endpoints, "CS explicit elective pool")
        assert_equal(elective.min_credits, groups[0][0], "CS elective credits")
        assert_equal((elective.subject_codes, elective.excluded_course_codes), ([], []), "CS extra filters")
        checks.extend(["breadth: 25 codes / 3 areas / 3 courses / 12 credits / 2 areas minimum", "electives: 12 credits / explicit codes and numeric interval"])
    elif plan.program_id == "ds-ms" and plan.pathway == "standard" and plan.concentration in DS_HEADINGS:
        rows = tables[DS_HEADINGS[plan.concentration]]
        groups = credit_groups(rows)
        selections = [node for node in children if node.kind == "select"]
        assert_equal([(node.min_credits, node.course_codes) for node in selections], groups, "DS concentration groups")
        if any(node.subject_codes or node.course_ranges or node.excluded_course_codes for node in selections):
            raise ValueError("Unexpected DS candidate filters")
        coop = next(node for node in children if node.kind == "optional")
        stack, coop_codes = [coop], []
        while stack:
            node = stack.pop()
            if node.course_code:
                coop_codes.append(node.course_code)
            stack.extend(node.children)
        start = rows.index("Optional Co-op")
        assert_equal(set(coop_codes), {code for row in rows[start + 1:] for code in row_codes(row)}, "DS optional co-op codes")
        checks = [f"concentration groups: {[(amount, len(codes)) for amount, codes in groups]}", "optional co-op pool"]
    elif plan.program_id == "info-ms" and plan.pathway == "standard" and plan.concentration == "general":
        options = next(node for node in children if node.kind == "any_of")
        assert_equal([branch.label for branch in options.children], ["Coursework Option", "Project Option", "Thesis Option"], "INFO alternatives")
        restricted = subject_pool(tables["Restricted Electives Course List"])
        other = subject_pool(tables["Other Electives Course List"])
        for branch in options.children:
            rows = tables[branch.label]
            source_minima = [amount for amount, _ in credit_groups(rows, allow_leading_courses=True)]
            selections = [node for node in branch.children if node.kind == "select"]
            assert_equal([node.min_credits for node in selections], source_minima, "INFO branch credits")
            assert_equal([node.course_code for node in branch.children if node.kind == "course"],
                         [code for row in rows if row.startswith("INFO") for code in row_codes(row)], "INFO branch project/thesis")
            if len(selections) != 2:
                raise ValueError("INFO branch must retain two pools")
            for node, source_pool in zip(selections, [restricted, other], strict=True):
                assert_equal((set(node.subject_codes), set(node.course_codes), set(node.excluded_course_codes)), source_pool, "INFO subjects/exclusions")
                assert_equal(node.course_ranges, [], "INFO unexpected ranges")
        checks = ["3 alternative exits / project-thesis courses / branch credit amounts", "2 subject pools / exact named exclusions"]
    elif plan.program_id == "info-ms" and plan.pathway == "bridge" and plan.concentration is None:
        assert_equal(required_groups(children[0]), source_required_groups(tables["Core Requirements"]), "INFO Bridge core groups")
        selections = [node for node in children if node.kind == "select"]
        if len(selections) != 2:
            raise ValueError("INFO Bridge must retain restricted and other groups")
        restricted, elective = selections
        assert_equal([(restricted.min_credits, restricted.course_codes)], credit_groups(tables["Restricted Electives"]), "INFO Bridge restricted pool")
        assert_equal((restricted.subject_codes, restricted.course_ranges, restricted.excluded_course_codes), ([], [], []), "INFO Bridge restricted filters")
        assert_equal((set(elective.subject_codes), set(elective.course_codes), set(elective.excluded_course_codes)),
                     subject_pool(tables["Electives"]), "INFO Bridge elective subjects/exclusions")
        assert_equal(elective.course_ranges, [], "INFO Bridge unexpected ranges")
        elective_amounts = [amount for amount, _ in credit_groups(tables["Electives"])]
        assert_equal([elective.min_credits], elective_amounts, "INFO Bridge elective credits")
        coop = next(node for node in children if node.kind == "optional")
        group = coop.children[0]
        if group.kind != "all_of" or len(group.children) != 2 or group.children[0].kind != "course" or group.children[1].kind != "any_of":
            raise ValueError("INFO Bridge optional Co-op needs preparation AND one alternative experience")
        work = group.children[1]
        if any(node.kind != "course" for node in work.children):
            raise ValueError("Unexpected Co-op experience shape")
        assert_equal({group.children[0].course_code, *(node.course_code for node in work.children)},
                     {code for row in tables["Optional Co-op Experience"] for code in row_codes(row)}, "INFO Bridge optional Co-op")
        checks = ["Bridge core main/lab groups", "12-credit restricted and elective pools with exact exclusions", "optional Co-op preparation AND alternative experience"]
    else:
        raise ValueError("No source-table audit adapter for this scope")
    return {"plan_id": plan.plan_id, "checks": checks, "coverage": plan.coverage,
            "limitation": "Candidate-table checks only, not full policy or eligibility verification"}


def cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-file", required=True, type=Path)
    parser.add_argument("--source-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        data = json.loads(args.plan_file.read_text(encoding="utf-8-sig"))
        if not isinstance(data, list) or not data:
            raise ValueError("Expected nonempty plan array")
        results = [audit_plan(ProgramPlan.model_validate(item), args.source_dir) for item in data]
        print(json.dumps(results, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, StopIteration) as exc:
        print(f"Offline source-table audit failed ({type(exc).__name__}); no files or database changed.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
