"""Course prerequisite logic is not a bag of mandatory edges."""

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from schemas.course_requisites import CatalogRequisites, RequisiteNode, RequisiteSection
from scrapers.course_requisites import parse_clause, parse_course_requisites

from scrapers.neu_catalog import _parse_courseblock


def entry(prerequisite="", corequisite=""):
    parts = ['<div class="courseblock"><p class="courseblocktitle">CS 5004. Design. (4 Hours)</p>']
    for label, text in [("Prerequisite(s)", prerequisite), ("Corequisite(s)", corequisite)]:
        if text:
            parts.append(f'<p class="courseblockextra"><strong>{label}: </strong>{text}</p>')
    parts.append('</div>')
    block = BeautifulSoup(''.join(parts), "html.parser").find("div", class_="courseblock")
    return _parse_courseblock(block, source_url="https://catalog.northeastern.edu/course-descriptions/cs/")


def test_courseblock_preserves_and_of_or_groups_and_grades():
    result = entry("(CS 5001 with a minimum grade of C- or CS 5010 with a minimum grade of B-); CS 5002 with a minimum grade of C-")
    rule = result.requisites.prerequisite.rule
    assert rule.kind == "all_of"
    assert rule.children[0].kind == "any_of"
    assert [(leaf.course_code, leaf.minimum_grade) for leaf in rule.children[0].children] == [("CS 5001", "C-"), ("CS 5010", "B-")]
    assert rule.children[1].course_code == "CS 5002"


def test_courseblock_corequisite_is_separate_from_prior_completion():
    result = entry(corequisite="CS 5005")
    assert result.requisites.prerequisite.status == "not_listed"
    assert result.requisites.corequisite.rule.course_code == "CS 5005"
    assert result.requisites.corequisite.status == "parsed"


@pytest.mark.parametrize("grade", ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "D-", "F", "P", "S"])
def test_minimum_grades_are_preserved_without_ranking_them(grade):
    section = parse_clause(f"CS 5001 with a minimum grade of {grade}")
    assert section.status == "parsed" and section.rule.minimum_grade == grade


@pytest.mark.parametrize("text", [
    "CS 5001 (may be taken concurrently) with a minimum grade of B-",
    "CS 5001 with a minimum grade of B- (may be taken concurrently)",
])
def test_explicit_concurrent_permission_is_not_a_plain_prior_course(text):
    rule = parse_clause(text).rule
    assert rule.concurrent_allowed is True and rule.minimum_grade == "B-"
    assert parse_clause("CS 5001").rule.concurrent_allowed is False


def test_academic_level_duplicate_branches_and_original_text_are_not_collapsed():
    text = "CS 5010 with a minimum grade of D- or CS 5010 with a minimum grade of C- (Graduate)"
    section = parse_clause(text)
    assert section.raw_text == text and section.rule.kind == "any_of"
    assert [node.minimum_grade for node in section.rule.children] == ["D-", "C-"]
    assert [node.academic_level for node in section.rule.children] == [None, "Graduate"]
    duplicate = parse_clause("CS 5001 with a minimum grade of C- or CS 5001 with a minimum grade of C-")
    assert len(duplicate.rule.children) == 2


def test_nested_or_of_and_groups_are_not_rearranged():
    section = parse_clause("((CS 5001 or CS 5002); CS 5004) or DS 5110")
    assert section.rule.kind == "any_of"
    assert section.rule.children[0].kind == "all_of"
    assert section.rule.children[0].children[0].kind == "any_of"
    assert section.rule.children[1].course_code == "DS 5110"


@pytest.mark.parametrize("text,reason", [
    ("CS 5001 or CS 5002 and CS 5004", "ambiguous_precedence"),
    ("Permission of instructor", "unsupported_syntax"),
    ("CS 5001 or consent of instructor", "unsupported_syntax"),
    ("CS 5001 with a minimum grade of Z", "unsupported_syntax"),
    ("CS 5001 with a minimum grade of C- and placement score 80", "unsupported_syntax"),
    ("CS 5001 (graduate students only)", "unsupported_syntax"),
    ("CS 5001, CS 5002", "unsupported_syntax"),
    ("CIS 200M with a minimum grade of D-", "unsupported_syntax"),
    ("(CS 5001 or CS 5002", "unbalanced_parentheses"),
    ("CS 5001)", "unbalanced_parentheses"),
    ("CS 5001;", "unsupported_syntax"),
    ("CS 5001 and", "unsupported_syntax"),
    ("", "empty_clause"),
])
def test_unrecognized_clause_retains_whole_text_without_partial_tree(text, reason):
    section = parse_clause(text)
    assert section.status == "unparsed" and section.rule is None
    assert section.raw_text == text and section.reason == reason


def test_formatting_is_normalized_but_not_semantic_operators():
    section = parse_clause("CS\xa05001\n with a minimum grade of C- ;\t CS 5002")
    assert section.raw_text == "CS 5001 with a minimum grade of C- ; CS 5002"
    assert section.rule.kind == "all_of"


def test_missing_empty_and_duplicate_sections_remain_distinct():
    assert parse_clause(None).status == "not_listed"
    assert parse_clause(" ").status == "unparsed"
    block = BeautifulSoup('''<div>
<p class="courseblockextra"><strong>Prerequisite(s): </strong>CS 5001</p>
<p class="courseblockextra"><strong>Prerequisite(s): </strong>CS 5002</p>
</div>''', "html.parser").div
    result = parse_course_requisites(block)
    assert result.prerequisite.reason == "duplicate_section"
    assert result.prerequisite.raw_text == "CS 5001\nCS 5002"
    assert result.prerequisite.rule is None and result.corequisite.status == "not_listed"


@pytest.mark.parametrize("label", ["Prerequisite(s): CS 5001", "<strong>Prerequisite(s)</strong> CS 5001", "Prerequisites: CS 5001"])
def test_malformed_requisite_label_does_not_become_not_listed(label):
    block = BeautifulSoup(f'<div><p class="courseblockextra">{label}</p></div>', "html.parser").div
    section = parse_course_requisites(block).prerequisite
    assert section.status == "unparsed" and section.reason == "malformed_section_label"
    assert "CS 5001" in section.raw_text


@pytest.mark.parametrize("text", ["(" * 12 + "CS 5001" + ")" * 12, "x" * 8001, " or ".join(["CS 5001"] * 121)])
def test_parser_budget_never_emits_an_oversized_partial_tree(text):
    section = parse_clause(text)
    assert section.status == "unparsed" and section.rule is None and section.raw_text == text


@pytest.mark.parametrize("payload", [
    {"kind": "course"},
    {"kind": "all_of", "children": [{"kind": "course", "course_code": "CS 5001"}]},
    {"kind": "course", "course_code": "CS 5001", "minimum_grade": "ZZ"},
    {"kind": "all_of", "minimum_grade": "B", "children": [{"kind": "course", "course_code": "CS 5001"}] * 2},
    {"kind": "any_of", "concurrent_allowed": True, "children": [{"kind": "course", "course_code": "CS 5001"}] * 2},
])
def test_invalid_node_shapes_do_not_masquerade_as_rules(payload):
    with pytest.raises(ValueError):
        RequisiteNode.model_validate(payload)


@pytest.mark.parametrize("payload", [
    {"status": "parsed", "raw_text": "CS 5001"},
    {"status": "not_listed", "raw_text": ""},
    {"status": "unparsed", "raw_text": "CS 5001", "reason": "unknown", "rule": {"kind": "course", "course_code": "CS 5001"}},
])
def test_section_state_is_not_allowed_to_claim_missing_or_partial_success(payload):
    with pytest.raises(ValueError):
        RequisiteSection.model_validate(payload)


def test_legacy_catalog_jsonl_is_unknown_and_new_json_roundtrips():
    from scrapers.neu_catalog import CatalogEntry
    legacy = CatalogEntry(course_code="CS 5004", course_name="Design", prereqs=["CS 5001"])
    assert legacy.requisites is None
    current = entry("CS 5001", "CS 5005")
    restored = CatalogEntry.model_validate_json(current.model_dump_json())
    assert restored.requisites == current.requisites
    assert CatalogRequisites.model_validate_json(current.requisites.model_dump_json()) == current.requisites


def test_new_capture_preserves_legacy_flat_fields_and_snapshot_hash():
    from db.catalog_source_repository import CatalogSourceRepository
    from scrapers.neu_catalog import CatalogEntry
    result = entry('<a class="bubblelink">CS 5001</a> or <a class="bubblelink">CS 5002</a>', "CS 5005")
    assert result.prereqs == ["CS 5001", "CS 5002"]
    old = result.model_dump(exclude={"requisites"})
    assert CatalogSourceRepository.snapshot(result).snapshot_id == CatalogSourceRepository.snapshot(CatalogEntry.model_validate(old)).snapshot_id


def test_historical_real_snapshot_parses_without_upgrading_its_edition():
    from scrapers.neu_catalog import _parse_dept_html
    root = Path(__file__).resolve().parent
    entries = _parse_dept_html((root / "fixtures/neu_catalog/dept_cs.html").read_text(encoding="utf-8"), source_url="https://catalog.northeastern.edu/course-descriptions/cs/")
    course = next(item for item in entries if item.course_code == "CS 5004")
    assert course.requisites.prerequisite.rule.kind == "all_of"
    assert course.requisites.corequisite.rule.course_code == "CS 5005"
    # This 2026-05-03 fixture has no capture manifest establishing current edition.
    assert "catalog_year" not in course.requisites.model_dump()


def test_current_ds_capstone_shape_retains_three_alternative_groups_and_last_required_course():
    # Curated clause from the captured DS 5500 block, not a complete policy.
    text = "(CS 5800 with a minimum grade of C- or EECE 7205 with a minimum grade of C-); (CS 6140 with a minimum grade of C- or DS 5220 with a minimum grade of C- or EECE 5644 with a minimum grade of C-); (CS 6220 with a minimum grade of C- or DS 5230 with a minimum grade of C- or IE 7275 with a minimum grade of C-); DS 5110 with a minimum grade of C-"
    rule = parse_clause(text).rule
    assert rule.kind == "all_of" and len(rule.children) == 4
    assert [child.kind for child in rule.children] == ["any_of", "any_of", "any_of", "course"]
    assert [[leaf.course_code for leaf in child.children] for child in rule.children[:3]] == [["CS 5800", "EECE 7205"], ["CS 6140", "DS 5220", "EECE 5644"], ["CS 6220", "DS 5230", "IE 7275"]]
    assert rule.children[3].course_code == "DS 5110"
    assert all(leaf.minimum_grade == "C-" for child in rule.children[:3] for leaf in child.children)
