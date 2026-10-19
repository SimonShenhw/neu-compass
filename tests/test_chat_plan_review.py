"""F review round (A19, B19; 2026-10-19): the positions and program name in the prompt, the plan year's wording,
recovery after a 409, panel and card wording, and the edges the reviewers' mutants reached.
中文：F 评审（A19、B19，2026-10-19）之后补的测试：提示词里的课程位置和项目全名、方案年度的说法、409 之后的恢复、
面板和卡片的文字，以及评审变异体触到的边界。只用合成课程、仓库策展方案和受控 MockTransport，不调模型、不联网。
"""

import copy
import json

import httpx
import pytest

from db.program_plan_repository import ProgramPlanRepository, content_hash
from llm.prompts.chat_v4 import PLAN_PART_BUDGET, PROMPT_TEMPLATE, format_courses_block, format_plan_block
from rag.answer_evidence import build_answer_evidence, build_plan_context
from rag.retriever import SearchHit
from schemas.course import Course
from schemas.course_program_context import CoursePlacement, course_placements
from schemas.plan_selection import PLAN_SELECTION_MESSAGES
from schemas.program_plan import ProgramPlan, RequirementNode
from tests.page_layout_support import install_backend, page, run
from tests.test_chat_plan_core import resolve, selection_data, stored
from tests.test_chat_plan_ui import choose, plan_curricula
from tests.test_chat_structured_requisites import document, seeded
from tests.test_program_plan_contract import chat_meta, stub_chat
from tests.test_program_plan_links import plans

PREFIX_CONFLICT = ("上方「你的项目（可选）」选的项目与问题里的专业前缀不一致；请改回「不指定」或改写问题。"
                   " (Selected program_id conflicts with the detected program prefix.)")


@pytest.fixture
def chat_page(monkeypatch):
    return plan_curricula(monkeypatch)


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


def panel(plan, *codes):
    from app.chat_plan_view import render_plan_context
    hits = hits_for(*codes)
    surface = Surface()
    render_plan_context(surface, build_plan_context(plan, [hit.course for hit in hits]).model_dump(mode="json"),
                        [{"course_id": hit.course.course_id, "primary_code": hit.course.primary_code} for hit in hits])
    return surface


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
                   "Cite the plan in words by program_name", "「方案版本（可选）」, which appears below 「你的项目（可选）」 only for"):
        assert phrase in text, phrase
    for removed in ("counts as explicitly named", "not rules applicable to this student", "suggest the plan selector instead",
                    "the program confirms)", "point to the evidence panel"):
        assert removed not in text, removed


def test_each_plan_409_says_the_question_was_not_answered_and_names_the_selector():
    from schemas.plan_selection import PLAN_SELECTOR_LABEL
    assert set(PLAN_SELECTION_MESSAGES) == {"missing", "stale", "draft", "unusable", "unavailable"}
    for text in PLAN_SELECTION_MESSAGES.values():
        assert "这个问题还没有回答；方案选择已清除。" in text and PLAN_SELECTOR_LABEL in text and "不选方案直接再问" in text


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


def test_unreadable_rows_keep_the_selected_year_and_the_card_says_nothing(empty_db):
    from app.answer_evidence_view import requisite_years_line
    from db.course_requisite_repository import CourseRequisiteRepository
    from db.repository import CourseRepository
    from tests.test_chat_structured_requisites import course
    first = seeded(empty_db, document())
    second = course(course_id="c-cs-6140", primary_code="CS 6140", primary_name="Machine Learning")
    CourseRepository(empty_db).insert(second, raw_text="")
    empty_db.execute("PRAGMA ignore_check_constraints=ON")
    empty_db.execute("UPDATE courses SET primary_name=CAST(x'ff' AS TEXT) WHERE course_id='c-cs-6140'")
    assert CourseRequisiteRepository(empty_db).read_batch([first.course_id, second.course_id]).unreadable == {second.course_id}
    evidence = build_answer_evidence(empty_db, [first, second], selected_year="2026-2027")[second.course_id]
    assert evidence.requisites.storage == "schema_unusable" and evidence.requisites.selected_year == "2026-2027"
    assert "requisite_year_not_recorded" in evidence.warnings
    assert requisite_years_line(evidence.model_dump(mode="json")) is None


def test_the_prompt_keeps_the_selected_year_and_the_other_years_count(empty_db):
    record = seeded(empty_db, document("2025-2026"), document("2026-2027"))
    evidence = build_answer_evidence(empty_db, [record], selected_year="2026-2027")
    block = json.loads(format_courses_block([SearchHit(course=record, score=1)], evidence))[0]
    assert (block["catalog_requisites"]["selected_year"], block["catalog_requisites"]["other_years_recorded"]) == ("2026-2027", 1)


@pytest.mark.parametrize("years,expected,absent", [
    (("2025-2026", "2026-2027"),
     "先修/共修规则：所选方案 Catalog 2026-2027 的课程块原文；另有 1 个其他年份未用于本次解释（不判断注册适用年度）", None),
    (("2026-2027",), "先修/共修规则：所选方案 Catalog 2026-2027 的课程块原文（不判断注册适用年度）", "另有"),
    (("2025-2026",), "所选方案 Catalog 2026-2027 没有可用的课程块规则；展示的其他年份不能替代。", "的课程块原文"),
    ((), "所选方案 Catalog 2026-2027 没有可用的课程块规则。", "展示的其他年份"),
])
def test_the_card_year_line_matches_what_was_shown(empty_db, years, expected, absent):
    from app.answer_evidence_view import requisite_years_line
    record = seeded(empty_db, *(document(year) for year in years))
    evidence = build_answer_evidence(empty_db, [record], selected_year="2026-2027")[record.course_id]
    line = requisite_years_line(evidence.model_dump(mode="json"))
    assert line == expected and (absent is None or absent not in line)


def test_the_card_year_line_is_silent_without_requisite_storage(empty_db):
    from app.answer_evidence_view import requisite_years_line
    record = seeded(empty_db, document())
    empty_db.execute("DROP TABLE course_requisite_documents")
    evidence = build_answer_evidence(empty_db, [record], selected_year="2026-2027")[record.course_id]
    assert evidence.requisites.storage == "schema_missing"
    assert requisite_years_line(evidence.model_dump(mode="json")) is None


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

def test_panel_names_partial_coverage_or_branches_unnamed_courses_and_positions_left_out():
    surface = panel(plan_where(concentration="engineering-theory-modeling"), "CS 5800", "ZZ 9999")
    assert any("仅部分规则" in text for text in surface.captions)
    assert any(text.startswith("CS 5800") and "上层有 OR 分支" in text for text in surface.texts)
    assert "ZZ 9999：方案里没有写到这门课；不代表不能算，也不代表能算，请向项目核实。" in surface.texts
    info = panel(plan_where(program_id="info-ms", pathway="standard"), "INFO 5200")
    assert "另有 2 处位置未列出，请到培养方案页核对完整规则。" in info.texts


def test_panel_shows_the_activation_text_and_never_calls_a_candidate_required():
    plan = with_rules(plan_where(pathway="align"), {"kind": "all_of", "label": "root", "children": [
        {"kind": "optional", "label": "co-op", "activate_when": "only with approval", "children": [
            {"kind": "course", "label": "leaf", "course_code": "CS 5800"}]},
        {"kind": "course", "label": "core", "course_code": "CS 5002"}]})
    assert any("仅适用于可选分支" in text and "条件：only with approval" in text for text in panel(plan, "CS 5800").texts)
    text = "\n".join(panel(plan_where(program_id="cs-ms", pathway="standard"), "CS 5200").texts)
    assert "组选候选" in text and "该组至少" in text and "必修课程" not in text


def test_each_course_set_guard_holds_on_its_own():
    from app.chat_plan_view import render_plan_context
    from app.state_manager import add_message
    context = build_plan_context(plan_where(pathway="align"), [Course(
        course_id="c", primary_code="CS 5800", primary_name="S")]).model_dump(mode="json")
    state = {"messages": []}
    add_message(state, role="assistant", content="a", evidence=[{"course_id": "other", "primary_code": "CS 5200",
                "primary_name": "S", "score": 1.0}], plan_context=context)
    assert "plan_context" not in state["messages"][-1]
    surface = Surface()
    render_plan_context(surface, context, [{"course_id": "other", "primary_code": "CS 5200"}])
    assert surface.captions == surface.texts == surface.markdowns == []


# Page: selector, re-selection and 409 recovery.

def test_the_plan_selector_explains_what_choosing_does(chat_page):
    box = choose(page()).selectbox(key="chat_plan_id")
    assert "不改变搜索结果" in box.help and "不判断你是否适用" in box.help


def test_a_revision_change_without_a_choice_is_silent(chat_page):
    backend, documents, calls = chat_page
    app = choose(page())
    documents["cs-ms"][1]["notes"] += " revised synthetic notes"
    run(app)
    assert not any("方案有更新" in item.value for item in app.caption)


def test_duplicate_scope_with_distinct_ids_is_not_selectable():
    from app.chat_plan_view import selectable_chat_plans
    items = [plan.model_dump(mode="json") for plan in plans() if plan.program_id == "cs-ms"]
    twin = copy.deepcopy(items[0]) | {"plan_id": items[0]["plan_id"] + "-twin"}
    assert selectable_chat_plans([items[0], twin], "cs-ms") == []


def test_the_student_can_go_back_to_no_plan(chat_page):
    from app.program_plan_view import PLAN_PLACEHOLDER
    backend, documents, calls = chat_page
    app = choose(page(), plan_id=plan_where(pathway="align").plan_id)
    box = app.selectbox(key="chat_plan_id")
    assert box.options[0] == PLAN_PLACEHOLDER
    box.set_value(None)
    run(app)
    app.chat_input[0].set_value("question without a plan again")
    run(app)
    assert "plan" not in backend.posts[-1]


def test_a_choice_made_again_after_a_revision_change_is_kept(chat_page):
    backend, documents, calls = chat_page
    align = plan_where(pathway="align")
    app = choose(page(), plan_id=align.plan_id)
    documents["cs-ms"][1]["notes"] += " revised synthetic notes"
    run(app)
    assert app.selectbox(key="chat_plan_id").value is None
    app.selectbox(key="chat_plan_id").set_value(align.plan_id)
    run(app)
    run(app)
    assert app.selectbox(key="chat_plan_id").value == align.plan_id
    assert not any("方案有更新" in item.value for item in app.caption)
    app.chat_input[0].set_value("question after choosing again")
    run(app)
    assert backend.posts[-1]["plan"]["plan_id"] == align.plan_id


def test_a_choice_made_again_after_a_plan_409_is_kept(chat_page, monkeypatch):
    backend, documents, calls = chat_page
    align = plan_where(pathway="align")
    original = type(backend).__call__

    def transport(self, request):
        if request.method == "POST" and not self.posts:
            self.posts.append(json.loads(request.content))
            return httpx.Response(409, json={"detail": PLAN_SELECTION_MESSAGES["stale"]})
        return original(self, request)

    monkeypatch.setattr(type(backend), "__call__", transport)
    app = choose(page(), plan_id=align.plan_id)
    app.chat_input[0].set_value("question")
    run(app)
    assert app.selectbox(key="chat_plan_id").value is None
    app.selectbox(key="chat_plan_id").set_value(align.plan_id)
    run(app)
    run(app)
    assert app.selectbox(key="chat_plan_id").value == align.plan_id
    app.chat_input[0].set_value("question again")
    run(app)
    assert backend.posts[-1]["plan"]["plan_id"] == align.plan_id


def test_a_family_switch_shows_no_revision_caption(chat_page):
    app = choose(page(), plan_id=plan_where(pathway="align").plan_id)
    app.selectbox(key="chat_program_id").set_value("ds-ms")
    run(app)
    assert not any("方案有更新" in item.value for item in app.caption)


def test_the_plan_panel_sits_before_the_course_list_and_old_answers_keep_their_plan(chat_page, monkeypatch):
    backend, documents, calls = chat_page
    align = plan_where(pathway="align")
    context = build_plan_context(align, [Course(course_id="c-algo", primary_code="CS 5800", primary_name="Synthetic Algorithms")])
    original = type(backend).__call__

    def transport(self, request):
        response = original(self, request)
        if request.method == "POST":
            events = [json.loads(line) for line in response.text.splitlines()]
            events[0]["plan_context"] = context.model_dump(mode="json")
            return httpx.Response(200, content="".join(json.dumps(event) + "\n" for event in events))
        return response

    monkeypatch.setattr(type(backend), "__call__", transport)
    app = choose(page(), plan_id=align.plan_id)
    app.chat_input[0].set_value("CS 5800")
    run(app)
    run(app)
    labels = [getattr(node, "label", None) for node in app.expander]
    assert labels.index("📘 所选方案与课程位置") < labels.index("📎 相关课程（1 门）")
    app.selectbox(key="chat_plan_id").set_value(None)
    run(app)
    assert any("本回答按方案" in item.value for item in app.caption)


def real_cache_page(monkeypatch, curriculum, post):
    """The real tab view cache over a MockTransport: GET /programs/cs-ms answers curriculum(n) on its nth fetch; a
    POST answers post(n) on the nth question, or the default backend when that returns None."""
    backend = install_backend(monkeypatch)
    backend.programs = [{"program_id": "cs-ms", "full_name": "cs-ms", "prefix": "CS"}]
    gets = []
    original = type(backend).__call__

    def transport(self, request):
        if request.method == "GET" and request.url.path == "/programs/cs-ms":
            gets.append(request.url.path)
            return httpx.Response(200, json={"program_id": "cs-ms", "plan_schema_available": True,
                                             "plans": copy.deepcopy(curriculum(len(gets)))})
        if request.method == "POST":
            response = post(len(self.posts) + 1)
            if response is not None:
                self.posts.append(json.loads(request.content))
                return response
        return original(self, request)

    monkeypatch.setattr(type(backend), "__call__", transport)
    return backend, gets


def test_a_program_conflict_409_keeps_the_plan_and_the_cached_list(monkeypatch):
    align = plan_where(pathway="align")
    documents = [plan.model_dump(mode="json") for plan in plans() if plan.program_id == "cs-ms"]
    backend, gets = real_cache_page(monkeypatch, lambda count: documents,
                                    lambda count: httpx.Response(409, json={"detail": PREFIX_CONFLICT}))
    app = choose(page(), plan_id=align.plan_id)
    app.chat_input[0].set_value("DS foundational courses")
    run(app)
    assert app.session_state["chat_plan_id"] == align.plan_id
    app.chat_input[0].set_value("rewritten question")
    run(app)
    assert [post["plan"]["plan_id"] for post in backend.posts] == [align.plan_id] * 2 and len(gets) == 1


def test_a_plan_409_refetches_the_family_list_so_choosing_again_sends_the_current_revision(monkeypatch):
    align = plan_where(pathway="align")
    first = [plan.model_dump(mode="json") for plan in plans() if plan.program_id == "cs-ms"]
    revised = copy.deepcopy(first)
    next(item for item in revised if item["plan_id"] == align.plan_id)["notes"] += " revised synthetic notes"
    backend, gets = real_cache_page(
        monkeypatch, lambda count: first if count == 1 else revised,
        lambda count: httpx.Response(409, json={"detail": PLAN_SELECTION_MESSAGES["stale"]}) if count == 1 else None)
    app = choose(page(), plan_id=align.plan_id)
    app.chat_input[0].set_value("first question")
    run(app)
    assert app.session_state["chat_plan_id"] is None
    app.selectbox(key="chat_plan_id").set_value(align.plan_id)
    run(app)
    app.chat_input[0].set_value("second question")
    run(app)
    expected = [content_hash(ProgramPlan.model_validate(next(item for item in documents if item["plan_id"] == align.plan_id)))
                for documents in (first, revised)]
    assert [post["plan"]["plan_content_sha256"] for post in backend.posts] == expected and len(gets) == 2


def test_a_plan_409_with_an_unchanged_list_keeps_the_programs_page_choice(monkeypatch):
    # Expired, not dropped: the refetch is still compared with the last list, so nothing reads as "updated".
    align = plan_where(pathway="align")
    documents = [plan.model_dump(mode="json") for plan in plans() if plan.program_id == "cs-ms"]
    backend, gets = real_cache_page(monkeypatch, lambda count: documents,
                                    lambda count: httpx.Response(409, json={"detail": PLAN_SELECTION_MESSAGES["unavailable"]}))
    app = choose(page(), plan_id=align.plan_id)
    app.session_state["program-plan-cs-ms"] = align.plan_id
    run(app)
    app.chat_input[0].set_value("question")
    run(app)
    assert len(gets) == 2 and app.session_state["chat_plan_id"] is None
    assert app.session_state["program-plan-cs-ms"] == align.plan_id
    assert "_program_plan_revised" not in app.session_state
