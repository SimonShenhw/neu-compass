"""F review round (A19, B19; 2026-10-19): the positions and program name in the prompt, the plan year's wording,
recovery after a 409, panel and card wording, and the edges the reviewers' mutants reached.
中文：F 评审（A19、B19，2026-10-19）之后补的测试：提示词里的课程位置和项目全名、方案年度的说法、409 之后的恢复、
面板和卡片的文字，以及评审变异体触到的边界。只用合成课程、仓库策展方案和受控 MockTransport，不调模型、不联网。
"""

import json
import re
from pathlib import Path

import pytest

from db.program_plan_repository import ProgramPlanRepository
from llm.prompts.chat_v4 import PLAN_PART_BUDGET, PROMPT_TEMPLATE, format_courses_block, format_plan_block
from rag.answer_evidence import build_answer_evidence, build_plan_context
from rag.retriever import SearchHit
from schemas.course import Course
from schemas.course_program_context import CoursePlacement, course_placements
from schemas.plan_selection import PLAN_SELECTION_MESSAGES
from schemas.program_plan import ProgramPlan, RequirementNode
from tests.test_chat_plan_core import resolve, selection_data, stored
from tests.test_chat_structured_requisites import document, seeded
from tests.test_program_plan_contract import chat_meta, stub_chat
from tests.program_plan_support import plans

ROOT = Path(__file__).resolve().parent.parent


def plan_where(**match):
    return next(plan for plan in plans() if all(getattr(plan, key) == value for key, value in match.items()))


def hits_for(*codes):
    return [SearchHit(course=Course(course_id=f"c{index}", primary_code=code, primary_name="Synthetic"), score=1.0)
            for index, code in enumerate(codes)]


def plan_block(prompt):
    return json.loads(prompt.split("# Selected program plan (JSON DATA)\n", 1)[1].split("\n\n# Conversation history", 1)[0])


def walk(node, path=()):
    here = (*path, node.label[:300])
    yield node, list(here)
    for child in node.children:
        yield from walk(child, here)


def with_rules(plan, requirements):
    return ProgramPlan.model_validate(plan.model_dump() | {"requirements": requirements})


class Surface:
    def __init__(self):
        self.captions, self.texts, self.markdowns = [], [], []

    def caption(self, text):
        self.captions.append(text)

    def text(self, text):
        self.texts.append(text)

    def markdown(self, text):
        self.markdowns.append(text)


# Prompt: positions, program name, budgets and rule wording.

def test_route_prompt_carries_the_meta_positions_in_hit_order_and_the_program_name(api_client, empty_db):
    plan = stored(empty_db)
    prompts = []
    stub_chat(api_client, prompts)
    meta = chat_meta(api_client.post("/chat", json={"query": "graph algorithms shortest paths",
                                                    "program_id": plan.program_id, "plan": selection_data(plan)}))
    assert len(meta["results"]) > 1
    placements = meta["plan_context"]["placements"]
    assert list(placements) == [item["course_id"] for item in meta["results"]]
    data = plan_block(prompts[-1])
    assert (data["program_id"], data["program_name"]) == (plan.program_id, "Synthetic program")
    assert (data["campus"], data["catalog_year"], data["pathway"]) == (plan.campus, plan.catalog_year, plan.pathway)
    assert "rules" in data and plan.source_url not in prompts[-1]
    assert [item["course"] for item in data["placements"]] == [item["primary_code"] for item in meta["results"]]
    for item, result in zip(data["placements"], meta["results"], strict=True):
        entries = placements[result["course_id"]]
        assert [(position["relation"], position["path"]) for position in item["positions"]] == [
            (entry["relation"], entry["path"]) for entry in entries]


def test_positions_keep_relation_path_minima_areas_and_the_count_left_out():
    info = plan_where(program_id="info-ms", pathway="standard")
    open_pool, excluded, unnamed = json.loads(format_plan_block(
        info, hits=hits_for("INFO 6105", "INFO 5200", "ZZ 9999")))["placements"]
    assert (open_pool["course"], len(open_pool["positions"]), open_pool["more_positions_not_shown"]) == ("INFO 6105", 4, 2)
    assert all(item["relation"] == "open_pool" and {"subject_codes", "course_ranges"} <= set(item)
               for item in open_pool["positions"])
    assert (excluded["course"], len(excluded["positions"]), excluded["more_positions_not_shown"]) == ("INFO 5200", 4, 2)
    assert all(item["relation"] == "excluded" and item["under_any_of"] is True and "subject_codes" not in item
               for item in excluded["positions"])
    assert unnamed == {"course": "ZZ 9999", "positions": []}
    (core,) = json.loads(format_plan_block(plan_where(pathway="align"), hits=hits_for("CS 5800")))["placements"]
    assert core["positions"][0]["relation"] == "required" and set(core["positions"][0]) == {"relation", "path"}
    assert "more_positions_not_shown" not in core
    (candidate,) = json.loads(format_plan_block(plan_where(program_id="cs-ms", pathway="standard"),
                                                hits=hits_for("CS 5200")))["placements"]
    pool = next(item for item in candidate["positions"] if item["relation"] == "select_candidate")
    assert pool["min_courses"] and pool["min_areas"] and pool["areas"]


def test_positions_carry_the_activation_text_and_or_ancestry():
    plan = with_rules(plan_where(pathway="align"), {"kind": "all_of", "label": "root", "children": [
        {"kind": "optional", "label": "co-op", "activate_when": "only with approval", "children": [
            {"kind": "any_of", "label": "either", "children": [
                {"kind": "course", "label": "leaf", "course_code": "CS 5800"},
                {"kind": "course", "label": "other", "course_code": "CS 5001"}]}]},
        {"kind": "course", "label": "core", "course_code": "CS 5002"}]})
    (item,) = json.loads(format_plan_block(plan, hits=hits_for("CS 5800")))["placements"]
    assert item["positions"] == [{"relation": "any_of_option", "path": ["root", "co-op", "either", "leaf"],
                                  "under_any_of": True, "activate_when": ["only with approval"]}]


def test_positions_have_their_own_budget_in_emitted_characters_and_never_cost_the_rules_tree():
    # Chinese labels, like the seeds': escaped or UTF-8-byte counting would drop the two courses' positions.
    codes = [f"CS {5001 + index}" for index in range(5)]
    plan = with_rules(plan_where(pathway="align"), {"kind": "all_of", "label": "规" * 300, "children": [
        {"kind": "select", "label": f"{index}" + "组" * 299, "course_codes": codes, "min_courses": 1} for index in range(6)]})
    few = json.loads(format_plan_block(plan, hits=hits_for(*codes[:2])))
    assert "rules" in few and [(len(item["positions"]), item["more_positions_not_shown"]) for item in few["placements"]] == [(4, 2)] * 2
    assert len(json.dumps(few["placements"], ensure_ascii=False)) <= PLAN_PART_BUDGET < len(json.dumps(few["placements"]))
    many = json.loads(format_plan_block(plan, hits=hits_for(*codes)))
    assert "rules" in many and "placements" not in many and many["placements_not_shown"] is True


def test_the_rules_budget_counts_the_emitted_characters():
    align = plan_where(pathway="align")
    for size in range(200, 300):
        data = json.loads(format_plan_block(with_rules(align, {"kind": "all_of", "label": "root", "children": [
            {"kind": "course", "label": "x" * size, "course_code": f"CS {5000 + index}"} for index in range(40)]})))
        assert data.pop("placements") == []
        assert len(json.dumps(data, ensure_ascii=False)) <= PLAN_PART_BUDGET, size
    data = json.loads(format_plan_block(with_rules(align, {"kind": "all_of", "label": "root", "children": [
        {"kind": "course", "label": "课" * 100, "course_code": f"CS {5000 + index}"} for index in range(40)]})))
    assert "rules" in data


def test_prompt_rules_use_the_positions_and_never_overclaim_the_plan_year():
    text = " ".join(PROMPT_TEMPLATE.split())
    for phrase in ("placements gives each retrieved course's positions", "A course the plan names gets no open_pool position",
                   "No positions means the plan neither names nor covers the course", "If placements_not_shown is true",
                   "name them only to state that rule", "not the student's own rule unless the student named that year",
                   "never call it unrecorded or not applicable", "never present one as that year's rule",
                   "another catalog year that has an entry here, explain that entry as that year's course block",
                   "only the program can confirm it", "point to the 「📘 所选方案与课程位置」 panel",
                   "Cite the plan in words by program_name",
                   "suggest choosing one under 「方案」, which appears once 「项目」 is set to a program with checked plans"):
        assert phrase in text, phrase
    # The Streamlit page's selectors (deleted in R8) are named no more. 中文：不再提 Streamlit 页的选择框（R8 已删）。
    for removed in ("counts as explicitly named", "not rules applicable to this student", "suggest the plan selector instead",
                    "the program confirms)", "point to the evidence panel", "方案版本（可选）", "你的项目（可选）"):
        assert removed not in text, removed


def test_each_plan_409_says_the_question_was_not_answered_and_names_the_selector():
    from schemas.plan_selection import PLAN_SELECTOR_LABEL
    assert set(PLAN_SELECTION_MESSAGES) == {"missing", "stale", "draft", "unusable", "unavailable"}
    for text in PLAN_SELECTION_MESSAGES.values():
        assert "这个问题还没有回答；方案选择已清除。" in text and f"「{PLAN_SELECTOR_LABEL}」" in text and "不选方案直接再问" in text
        assert "上方" not in text and "（可选）" not in text


def test_the_plan_409_details_are_the_web_front_ends_own_sentences():
    """The web words these refusals from `reason` (web/src/models/chatFailure.ts); API clients get its sentences.
    中文：新前端按 reason 说话；API 的 detail 和它的说法逐字相同。"""
    source = (ROOT / "web/src/models/chatFailure.ts").read_text(encoding="utf-8")
    retry = re.search(r"const planRetry =\s*'([^']*)';", source)
    assert retry
    for outcome, text in PLAN_SELECTION_MESSAGES.items():
        entry = re.search(rf"\[\s*'plan_{outcome}',\s*'([^']*)'(\s*\+\s*planRetry)?,?\s*\]", source)
        assert entry, outcome
        assert text == entry.group(1) + (retry.group(1) if entry.group(2) else ""), outcome


def test_the_prompt_refuses_positions_from_another_plan_or_for_other_courses():
    align, standard = plan_where(pathway="align"), plan_where(program_id="cs-ms", pathway="standard")
    hits = hits_for("CS 5800")
    with pytest.raises(ValueError):
        format_plan_block(align, build_plan_context(standard, [hits[0].course]), hits)
    other = Course(course_id="other", primary_code="CS 5001", primary_name="Synthetic")
    with pytest.raises(ValueError):
        format_plan_block(align, build_plan_context(align, [other]), hits)


def test_a_draft_never_reaches_the_prompt_and_the_scope_names_the_concentration():
    align = plan_where(pathway="align")
    draft = ProgramPlan.model_validate(align.model_dump() | {"review_status": "draft"})
    with pytest.raises(ValueError):
        format_plan_block(draft)
    # Not even beside a checked context of the same plan ID.
    with pytest.raises(ValueError):
        format_plan_block(draft, build_plan_context(align, []), [])
    plan = plan_where(concentration="engineering-theory-modeling")
    assert json.loads(format_plan_block(plan))["concentration"] == "engineering-theory-modeling"


# Requisite years under a selected plan, in the evidence, the prompt and the card.

def test_a_missing_selected_year_must_count_every_shown_edition(empty_db):
    from schemas.answer_evidence import RequisiteEvidence
    record = seeded(empty_db, document("2025-2026"))
    requisites = build_answer_evidence(empty_db, [record], selected_year="2026-2027")[record.course_id].requisites
    assert requisites.other_years_recorded == 1
    with pytest.raises(ValueError):
        RequisiteEvidence.model_validate(requisites.model_dump() | {"other_years_recorded": 0})


def test_the_prompt_keeps_the_selected_year_and_the_other_years_count(empty_db):
    record = seeded(empty_db, document("2025-2026"), document("2026-2027"))
    evidence = build_answer_evidence(empty_db, [record], selected_year="2026-2027")
    block = json.loads(format_courses_block([SearchHit(course=record, score=1)], evidence))[0]
    assert (block["catalog_requisites"]["selected_year"], block["catalog_requisites"]["other_years_recorded"]) == ("2026-2027", 1)


# Resolution edges.

def test_a_draft_with_another_revision_is_stale_not_draft(empty_db):
    plan = stored(empty_db)
    draft = ProgramPlan.model_validate(plan.model_dump() | {"review_status": "draft"})
    ProgramPlanRepository(empty_db).store(draft, allow_downgrade=True)
    assert resolve(empty_db, draft, plan_content_sha256="0" * 64).outcome == "stale"
    assert resolve(empty_db, draft).outcome == "draft"


def test_a_null_document_in_a_keyless_copy_is_unusable(empty_db):
    plan = stored(empty_db)
    empty_db.execute("CREATE TABLE copied AS SELECT * FROM program_plans")
    empty_db.execute("DROP TABLE program_plans")
    empty_db.execute("ALTER TABLE copied RENAME TO program_plans")
    empty_db.execute("UPDATE program_plans SET document=NULL")
    assert resolve(empty_db, plan).outcome == "unusable"


def test_a_valid_plan_over_the_size_budget_is_unusable(empty_db):
    codes = [f"CS {5000 + index}" for index in range(100)]
    plan = with_rules(plan_where(pathway="align"), {"kind": "all_of", "label": "root", "children": [
        {"kind": "all_of", "label": f"group {group}", "children": [
            {"kind": "select", "label": "x" * 1000, "course_codes": codes, "min_courses": 1} for _ in range(38)]}
        for group in range(3)]})
    assert len(plan.model_dump_json()) > 200_000
    stored(empty_db, plan)
    assert resolve(empty_db, plan).outcome == "unusable"


# Placements on the seeds and synthetic trees.

def test_ties_keep_tree_order_before_the_cap():
    info = plan_where(program_id="info-ms", pathway="standard")
    excluded = [path for node, path in walk(info.requirements)
                if node.kind == "select" and "INFO 5200" in node.excluded_course_codes]
    entries, omitted = course_placements(info.requirements, "INFO 5200")
    assert [entry.path for entry in entries] == excluded[:4] and omitted == len(excluded) - 4
    pools = [path for node, path in walk(info.requirements) if node.kind == "select" and (
        "INFO" in node.subject_codes or any(item.contains("INFO 6105") for item in node.course_ranges))]
    entries, omitted = course_placements(info.requirements, "INFO 6105")
    assert [entry.path for entry in entries] == pools[:4] and omitted == len(pools) - 4


def test_seed_candidates_never_also_get_an_open_pool():
    for plan in plans():
        candidates = sorted({code for node, _ in walk(plan.requirements) if node.kind == "select" for code in node.course_codes})
        for code in candidates:
            assert all(entry.relation != "open_pool" for entry in course_placements(plan.requirements, code)[0]), (plan.plan_id, code)


def test_an_exclusion_counts_as_named():
    tree = RequirementNode(kind="all_of", label="root", children=[
        RequirementNode(kind="select", label="pool A", subject_codes=["CS"], excluded_course_codes=["CS 5010"], min_credits=4),
        RequirementNode(kind="select", label="pool B", subject_codes=["CS"], min_credits=8)])
    assert [entry.relation for entry in course_placements(tree, "CS 5010")[0]] == ["excluded"]


def test_placement_bounds_match_the_plan_schema():
    CoursePlacement(path=["x" * 300], relation="required")
    with pytest.raises(ValueError):
        CoursePlacement(path=["x" * 301], relation="required")
    long_area = "a" * 301
    pool = RequirementNode(kind="select", label="pool", course_codes=["CS 5800", "CS 5200"], min_courses=1,
                           areas={long_area: ["CS 5800"], "b": ["CS 5200"]})
    entries, _ = course_placements(RequirementNode(kind="all_of", label="root", children=[
        pool, RequirementNode(kind="course", label="leaf", course_code="CS 5001")]), "CS 5800")
    assert entries[0].areas == [long_area[:300]]
    align = plan_where(pathway="align")
    projected = json.loads(format_plan_block(with_rules(align, {"kind": "all_of", "label": "root", "children": [
        pool.model_dump(), {"kind": "course", "label": "leaf", "course_code": "CS 5001"}]})))
    assert len(projected["rules"]["all_of"][0]["select"]["areas"][0]["name"]) == 300
    optional = RequirementNode(kind="optional", label="opt", activate_when="w" * 500, children=[
        RequirementNode(kind="course", label="leaf", course_code="CS 5800")])
    assert course_placements(optional, "CS 5800")[0][0].activate_when == ["w" * 500]
    node = {"kind": "course", "label": "leaf", "course_code": "CS 5800"}
    for level in range(7):  # 7 optional levels + a leaf = the plan schema's maximum depth of 8
        node = {"kind": "optional", "label": f"level {level}", "activate_when": "when", "children": [node]}
    entries, _ = course_placements(with_rules(align, node).requirements, "CS 5800")
    assert len(entries[0].path) == 8


def test_an_archived_source_must_match_the_plan_year():
    from schemas.answer_evidence import PlanContext
    context = build_plan_context(plan_where(pathway="align"), [Course(course_id="c", primary_code="CS 5800", primary_name="S")])
    data = context.model_dump(mode="json") | {
        "source_url": "https://catalog.northeastern.edu/archive/2025-2026/graduate/computer-science/"}
    with pytest.raises(ValueError):
        PlanContext.model_validate_json(json.dumps(data))


# Evidence panel and history.


# Page: selector, re-selection and 409 recovery.
