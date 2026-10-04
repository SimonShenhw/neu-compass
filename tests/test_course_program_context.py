"""Explicit matches and manual scope selection, not merged grade requirements."""

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app.course_requisite_view import render_course_requisites
from db.course_requisite_repository import CourseRequisiteRepository
from db.program_plan_repository import ProgramPlanRepository
from db.program_repository import ProgramRepository
from schemas.course_description_evidence import CourseDescriptionEvidence
from schemas.course_program_context import CourseProgramContext, explicitly_mentions
from schemas.course_requisite_document import CourseRequisiteListing
from schemas.program import Program
from schemas.program_plan import ProgramPlan, RequirementNode
from tests.test_course_requisite_contract import source_document
from tests.test_course_requisite_storage import document, target
from tests.test_course_requisite_view import FakeSt, app_source

ROOT = Path(__file__).resolve().parent.parent


def plan(**changes):
    data = json.loads((ROOT / "data/program_plan_seed/boston_2026_2027_pathway_rules.json").read_text(encoding="utf-8"))[0]
    return ProgramPlan.model_validate({**data, **changes})


def seed(conn, item):
    repo = ProgramRepository(conn)
    if conn.execute("SELECT 1 FROM programs WHERE program_id=?", (item.program_id,)).fetchone() is None:
        repo.upsert_program(Program(program_id=item.program_id, full_name="Test program", prefix="CS"))
    ProgramPlanRepository(conn).store(item)
    return item


@pytest.mark.parametrize("node,expected", [
    ({"kind": "course", "label": "Explicit", "course_code": "CS 5004"}, True),
    ({"kind": "select", "label": "Finite", "course_codes": ["CS 5004", "CS 5008"], "min_courses": 1}, True),
    ({"kind": "select", "label": "Excluded", "course_codes": ["CS 5004", "CS 5008"], "excluded_course_codes": ["CS 5004"], "min_courses": 1}, False),
    ({"kind": "select", "label": "Open", "subject_codes": ["CS"], "min_credits": 4}, False),
    ({"kind": "select", "label": "Range", "course_ranges": [{"start": "CS 5000", "end": "CS 5999"}], "min_credits": 4}, False),
    ({"kind": "condition", "label": "CS 5004 is mentioned only in prose"}, False),
    ({"kind": "course", "label": "Another CS 5004", "course_code": "CS 5008"}, False),
])
def test_only_explicit_leaf_or_unexcluded_finite_candidate_matches(node, expected):
    assert explicitly_mentions(RequirementNode.model_validate(node), "CS 5004") is expected


def test_optional_branch_match_does_not_remove_optional_activation():
    node = RequirementNode(kind="optional", label="Optional thesis", activate_when="Only if selected",
        children=[RequirementNode(kind="course", label="Not common mandatory", course_code="CS 5004")])
    assert explicitly_mentions(node, "CS 5004") and node.activate_when == "Only if selected"


def test_same_year_context_keeps_all_scopes_and_does_not_merge_grades(empty_db):
    target(empty_db)
    course_repo = CourseRequisiteRepository(empty_db)
    course_repo.store(document())
    align = seed(empty_db, plan())
    seattle = seed(empty_db, plan(plan_id="cs-ms-seattle-2026-2027-align", campus="seattle"))
    older = seed(empty_db, plan(plan_id="cs-ms-boston-2025-2026-align", catalog_year="2025-2026", source_catalog_year="2025-2026"))
    bundle = course_repo.list_for_course("target")
    context = bundle.program_contexts[0]
    assert {item.plan_id for item in context.plans} == {align.plan_id, seattle.plan_id}
    assert older.plan_id not in {item.plan_id for item in context.plans}
    assert bundle.documents[0].requisites.prerequisite.rule.children[0].minimum_grade == "B-"
    assert "每门 B 或以上" in context.plans[0].model_dump_json()
    assert course_repo.list_for_course("target", catalog_year="2024-2025").program_contexts == []


@pytest.mark.parametrize("kind", ["digest", "json", "column-scope", "identity", "oversize"])
def test_corrupt_same_year_plan_is_isolated_not_replaced_with_seed(empty_db, kind):
    seed(empty_db, plan())
    if kind == "digest":
        empty_db.execute("UPDATE program_plans SET content_hash='bad'")
    elif kind == "json":
        empty_db.execute("UPDATE program_plans SET document='[]'")
    elif kind == "column-scope":
        empty_db.execute("UPDATE program_plans SET campus='seattle'")
    elif kind == "identity":
        empty_db.execute("UPDATE program_plans SET plan_id='another-id'")
    else:
        empty_db.execute("UPDATE program_plans SET document=?", (json.dumps("x" * 200_001),))
    context = ProgramPlanRepository(empty_db).course_context("CS 5004", "2026-2027")
    assert context.plans == [] and context.unusable_records == 1
    assert "program_context_records_unusable" in context.warnings


def test_draft_context_and_broken_table_are_explicit_not_inferred(empty_db):
    seed(empty_db, plan(review_status="draft", checked_by=None, checked_on=None))
    repo = ProgramPlanRepository(empty_db)
    context = repo.course_context("CS 5004", "2026-2027")
    assert context.plans == [] and context.unreviewed_records == 1
    empty_db.execute("DROP TABLE program_plans")
    empty_db.execute("CREATE TABLE program_plans (plan_id TEXT)")
    context = repo.course_context("CS 5004", "2026-2027")
    assert context.schema_available and context.plans == [] and "program_context_schema_unusable" in context.warnings


def test_broken_table_duplicate_identity_has_no_first_match_winner(empty_db):
    seed(empty_db, plan())
    row = tuple(empty_db.execute("SELECT * FROM program_plans").fetchone())
    empty_db.execute("DROP TABLE program_plans")
    empty_db.execute("CREATE TABLE program_plans (plan_id TEXT,program_id TEXT,campus TEXT,catalog_year TEXT,pathway TEXT,concentration TEXT,document TEXT,content_hash TEXT)")
    empty_db.executemany("INSERT INTO program_plans VALUES(?,?,?,?,?,?,?,?)", [row, row])
    context = ProgramPlanRepository(empty_db).course_context("CS 5004", "2026-2027")
    assert context.plans == [] and context.unusable_records == 2
    assert "program_context_duplicate_identity_or_scope" in context.warnings


def test_no_explicit_match_does_not_mean_no_policy_or_borrow_latest(empty_db):
    seed(empty_db, plan())
    context = ProgramPlanRepository(empty_db).course_context("INFO 7405", "2026-2027")
    assert context.plans == [] and "no_match_is_not_no_program_policy" in context.warnings
    older = ProgramPlanRepository(empty_db).course_context("CS 5004", "2025-2026")
    assert older.plans == [] and older.unusable_records == 0


@pytest.mark.parametrize("year", ["latest", "2026-2028", "2026-2027' OR 1=1"])
def test_context_scope_validation_rejects_guessing_or_sql(year, empty_db):
    with pytest.raises(ValueError):
        ProgramPlanRepository(empty_db).course_context("CS 5004", year)


def test_program_context_is_read_time_not_persisted_in_course_json_or_hash(empty_db):
    target(empty_db)
    repo = CourseRequisiteRepository(empty_db)
    repo.store(document())
    before = tuple(empty_db.execute("SELECT document,content_hash FROM course_requisite_documents").fetchone())
    assert repo.list_for_course("target").program_contexts[0].plans == []
    seed(empty_db, plan())
    assert len(repo.list_for_course("target").program_contexts[0].plans) == 1
    assert tuple(empty_db.execute("SELECT document,content_hash FROM course_requisite_documents").fetchone()) == before
    empty_db.execute("UPDATE program_plans SET content_hash='bad'")
    assert repo.list_for_course("target").program_contexts[0].plans == []
    assert tuple(empty_db.execute("SELECT document,content_hash FROM course_requisite_documents").fetchone()) == before


def test_detail_and_filtered_api_include_only_matching_usable_editions(api_client, empty_db):
    doc = source_document()
    evidence = CourseDescriptionEvidence.from_paragraphs(["No permission is required for teamwork."])
    CourseRequisiteRepository(empty_db).store(doc.model_copy(update={"description_evidence": evidence}))
    stored_plan = seed(empty_db, plan())  # Explicit CS 5800 core, independent bridge conditions.
    detail = api_client.get("/course/c-cs-5800").json()["course_requisites"]
    assert detail["documents"][0]["description_evidence"]["status"] == "review_needed"
    assert detail["program_contexts"][0]["plans"][0]["plan_id"] == stored_plan.plan_id
    filtered = api_client.get("/course/c-cs-5800/requisites", params={"catalog_year": "2024-2025"}).json()
    assert filtered["program_contexts"] == []
    empty_db.execute("DROP TABLE program_plans")
    body = api_client.get("/course/c-cs-5800/requisites").json()
    assert body["documents"] and not body["program_contexts"][0]["schema_available"]
    assert not ProgramPlanRepository(empty_db).available()


@pytest.mark.parametrize("kind", ["wrong-year", "wrong-course", "duplicate", "draft", "wrong-url"])
def test_context_bundle_rejects_wrong_or_duplicate_scope(kind):
    doc = document(course_id="design")
    data = CourseRequisiteListing(schema_available=True, documents=[doc], program_contexts=[
        CourseProgramContext(course_code="CS 5004", catalog_year="2026-2027", schema_available=True, plans=[plan()])]).model_dump(mode="json")
    context = data["program_contexts"][0]
    if kind == "wrong-year":
        context["catalog_year"] = "2025-2026"
    elif kind == "wrong-course":
        context["course_code"] = "CS 5008"  # Both mentioned; still cannot bind context to a different course.
    elif kind == "duplicate":
        context["plans"] *= 2
    elif kind == "draft":
        context["plans"][0]["review_status"] = "draft"
    else:
        context["plans"][0]["source_url"] = "https://evil.test/"
    with pytest.raises(ValueError):
        CourseRequisiteListing.model_validate(data)


def ui_bundle():
    doc = document(course_id="design")
    doc.description_evidence = CourseDescriptionEvidence.from_paragraphs([
        'Students may seek permission. <script>bad()</script>', "No approval is required for teamwork."])
    context = CourseProgramContext(course_code="CS 5004", catalog_year="2026-2027", schema_available=True, plans=[plan()])
    return CourseRequisiteListing(schema_available=True, has_any_stored_records=True, documents=[doc], program_contexts=[context]).model_dump(mode="json")


class ScopeSt(FakeSt):
    def __init__(self, path=None):
        super().__init__("2026-2027")
        self.path = path
    def selectbox(self, label, options, **kwargs):
        choice = self.choice if kwargs["key"] == "year" else self.path
        assert choice in options
        return choice


def test_ui_description_is_plain_text_and_program_scope_default_is_none():
    st = ScopeSt()
    render_course_requisites(st, ui_bundle(), course_id="design", course_code="CS 5004", course_name="Design", key="year")
    assert 'Students may seek permission. <script>bad()</script>' in st.texts
    assert all("<script>" not in text for text in st.markdowns)
    assert not any("每门 B 或以上" in text for text in st.texts)
    st = ScopeSt(plan().plan_id)
    st.session_state["year-program-2026-2027"] = "stale-plan-id"
    render_course_requisites(st, ui_bundle(), course_id="design", course_code="CS 5004", course_name="Design", key="year")
    assert "year-program-2026-2027" not in st.session_state
    assert any("每门 B 或以上" in text for text in st.texts)
    assert any("最低成绩：B-" in text for text in st.texts)
    assert any("用途不同" in text for text in st.captions)


@pytest.mark.parametrize("paragraphs,phrase", [(None, "未捕获"), ([], "未列出 description"), (["Studies software."], "未匹配当前有限关键词")])
def test_ui_distinguishes_old_missing_and_keyword_no_match(paragraphs, phrase):
    data = ui_bundle()
    data["program_contexts"] = []
    data["documents"][0]["description_evidence"] = None if paragraphs is None else CourseDescriptionEvidence.from_paragraphs(paragraphs).model_dump(mode="json")
    st = ScopeSt()
    render_course_requisites(st, data, course_id="design", course_code="CS 5004", course_name="Design", key="year")
    assert any(phrase in text for text in st.texts)


def test_wrong_context_source_is_not_rendered_as_link_or_personal_path():
    data = ui_bundle()
    data["program_contexts"][0]["plans"][0]["source_url"] = "https://evil.test/"
    st = ScopeSt()
    render_course_requisites(st, data, course_id="design", course_code="CS 5004", course_name="Design", key="year")
    assert st.warnings and not st.texts
    assert not any("evil.test" in text for text in st.markdowns)


def test_free_text_program_scope_notes_and_rule_labels_are_not_markup():
    data = ui_bundle()
    stored = data["program_contexts"][0]["plans"][0]
    payload = '[click](https://evil.test/) <script>bad()</script>'
    stored["program_id"] = payload
    stored["concentration"] = payload
    stored["notes"] = payload
    stored["requirements"]["children"][-1]["label"] = payload
    st = ScopeSt(plan().plan_id)
    render_course_requisites(st, data, course_id="design", course_code="CS 5004", course_name="Design", key="year")
    assert any(payload in text for text in st.texts)
    assert not any("evil.test" in text for text in st.markdowns + st.captions)


def test_real_widget_separate_year_and_path_selection_plain_text_no_old_graph():
    app = AppTest.from_string(app_source(ui_bundle())).run(timeout=45)
    # One recorded edition is shown by default (review 2026-10-03); the program
    # path below it still requires an explicit choice.
    assert not app.exception and app.selectbox[0].value == "2026-2027"
    assert len(app.selectbox) == 2 and app.selectbox[1].value is None
    app.selectbox[0].set_value("2026-2027").run(timeout=45)
    assert not app.exception and len(app.selectbox) == 2 and app.selectbox[1].value is None
    assert any("<script>" in item.value for item in app.text)
    assert not any("<script>" in item.value for item in app.markdown)
    assert not any("每门 B 或以上" in item.value for item in app.text)
    app.selectbox[1].set_value(plan().plan_id).run(timeout=45)
    assert not app.exception and any("每门 B 或以上" in item.value for item in app.text)
    assert any("最低成绩：B-" in item.value for item in app.text)
    assert len(app.get("graphviz_chart")) == 0
    app.selectbox[0].set_value(None).run(timeout=45)
    assert not app.exception and len(app.text) == 0 and len(app.selectbox) == 1
    app.selectbox[0].set_value("2026-2027").run(timeout=45)
    assert not app.exception and app.selectbox[1].value is None
