"""Frozen whole-tree snapshots plus named semantic checks; snapshots alone are not an oracle."""

import json

from schemas.plan_draft import DraftCourse, evaluate_draft
from tests.plan_draft_support import SNAPSHOT, seed_documents, snapshot_text, synthetic_courses


def walk(node):
    yield node
    for child in node.children:
        yield from walk(child)


def test_ten_seed_snapshots_byte_identical_and_all_partial_roots_non_met():
    assert snapshot_text() == SNAPSHOT.read_text(encoding="utf-8")
    records = json.loads(snapshot_text())
    assert len(records) == 10 and len({(r["seed"], r["plan_id"]) for r in records}) == 10
    assert all(r["result"]["root"]["status"] != "met" for r in records)
    assert all(p.coverage == "partial" and p.review_status == "source_checked" for _, p in seed_documents())
    assert any("align" in r["plan_id"] for r in records)
    assert any("general" in r["plan_id"] for r in records)
    assert any("engineering-theory-modeling" in r["plan_id"] for r in records)


def test_etm_actual_shared_candidate_is_unknown_when_needed_by_both_groups():
    plan = next(p for _, p in seed_documents() if "engineering-theory-modeling" in p.plan_id)
    result = evaluate_draft(plan, [DraftCourse(course_id="synthetic-eece", code="EECE 5360", name="Synthetic", credits=12)])
    pools = [n for n in walk(result.root) if n.kind == "select" and "EECE 5360" in n.counted]
    assert len(pools) == 2 and all(n.status == "unknown" for n in pools)
    assert all(any("重复计入" in reason for reason in n.reasons) for n in pools)


def test_msis_open_pool_and_align_optional_conditions_do_not_become_met():
    general = next(p for seed, p in seed_documents() if seed == "boston_2026_2027_extended_rules.json" and "standard-general" in p.plan_id)
    result = evaluate_draft(general, synthetic_courses(general))
    opened = [n for n in walk(result.root) if n.kind == "select" and n.possible]
    assert opened and all(n.status != "met" for n in opened)
    align = next(p for _, p in seed_documents() if p.pathway == "align")
    result = evaluate_draft(align, synthetic_courses(align))
    options = [n for n in walk(result.root) if n.kind == "optional"]
    assert options and all(n.status == "not_evaluated" for n in options)
    assert all(child.status is None for n in options for child in n.children)
