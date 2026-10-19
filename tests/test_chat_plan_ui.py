"""F widgets and request/history integration with guarded MockTransport only."""

import copy
import json

import httpx
import pytest

from db.program_plan_repository import content_hash
from tests.page_layout_support import install_backend, page, run
from tests.test_program_plan_links import plans


@pytest.fixture
def chat_page(monkeypatch):
    import app.program_view as programs
    backend = install_backend(monkeypatch)
    backend.programs = [{"program_id": family, "full_name": family, "prefix": prefix}
                        for family, prefix in (("cs-ms", "CS"), ("ds-ms", "DS"))]
    documents = {family: [plan.model_dump(mode="json") for plan in plans() if plan.program_id == family]
                 for family in ("cs-ms", "ds-ms")}
    calls = []

    def curriculum(st, family):
        calls.append(family)
        return {"program_id": family, "plan_schema_available": True, "plans": copy.deepcopy(documents[family])}

    monkeypatch.setattr(programs, "get_curriculum_cached", curriculum)
    return backend, documents, calls


def choose(app, family="cs-ms", plan_id=None):
    from schemas.plan_selection import PLAN_SELECTOR_LABEL
    app.selectbox(key="chat_program_id").set_value(family)
    run(app)
    box = app.selectbox(key="chat_plan_id")
    assert box.label == PLAN_SELECTOR_LABEL and box.value is None
    if plan_id:
        box.set_value(plan_id)
        run(app)
    return app


def test_chat_plan_selector_is_absent_without_family_and_defaults_empty(chat_page):
    backend, documents, calls = chat_page
    app = page()
    assert calls == [] and not [box for box in app.selectbox if box.key == "chat_plan_id"]
    choose(app)
    assert app.selectbox(key="chat_plan_id").value is None and not backend.posts
    app.chat_input[0].set_value("question without selected plan")
    run(app)
    assert backend.posts[-1]["program_id"] == "cs-ms" and "plan" not in backend.posts[-1]


def test_chat_options_only_include_checked_unambiguous_current_family():
    from app.chat_plan_view import selectable_chat_plans
    items = [plan.model_dump(mode="json") for plan in plans() if plan.program_id == "cs-ms"]
    assert len(selectable_chat_plans(items, "cs-ms")) == 2
    assert selectable_chat_plans(items, "ds-ms") == []
    draft = copy.deepcopy(items[0]); draft["review_status"] = "draft"
    assert selectable_chat_plans([draft], "cs-ms") == []
    assert selectable_chat_plans([items[0], items[0]], "cs-ms") == []
    assert selectable_chat_plans([{"bad": "format"}], "cs-ms") == []


def test_selected_request_carries_exact_scope_revision_and_history_keeps_the_validated_panel(chat_page, monkeypatch):
    from rag.answer_evidence import build_plan_context
    from schemas.course import Course
    backend, documents, calls = chat_page
    plan = next(plan for plan in plans() if plan.pathway == "align")
    context = build_plan_context(plan, [Course(course_id="c-algo", primary_code="CS 5800", primary_name="Synthetic Algorithms")])
    original = type(backend).__call__

    def transport(self, request):
        response = original(self, request)
        if request.method == "POST":
            events = [json.loads(line) for line in response.text.splitlines()]
            events[0]["plan_context"] = context.model_dump(mode="json")
            return httpx.Response(200, content="".join(json.dumps(event) + "\n" for event in events))
        return response

    monkeypatch.setattr(type(backend), "__call__", transport)
    app = choose(page(), plan_id=plan.plan_id)
    app.chat_input[0].set_value("CS 5800")
    run(app)
    sent = backend.posts[-1]
    assert sent["plan"] == {name: getattr(plan, name) for name in (
        "program_id", "plan_id", "campus", "catalog_year", "pathway", "concentration")} | {"plan_content_sha256": content_hash(plan)}
    message = app.session_state["messages"][-1]
    assert message["plan_context"] == context.model_dump(mode="json")
    run(app)
    assert any("本回答按方案" in value.value for value in app.caption)
    assert any("CS 5800" in value.value and "必修" in value.value for value in app.text)
    assert any(plan.source_url in value.value for value in app.markdown)


def test_changing_family_resets_plan_before_creating_its_widget(chat_page):
    plan = next(plan for plan in plans() if plan.pathway == "align")
    app = choose(page(), plan_id=plan.plan_id)
    app.selectbox(key="chat_program_id").set_value("ds-ms")
    run(app)
    assert app.selectbox(key="chat_plan_id").value is None
    assert app.session_state["chat_plan_id"] is None


def test_revision_change_drops_choice_and_only_notifies_once(chat_page):
    backend, documents, calls = chat_page
    plan = next(plan for plan in plans() if plan.pathway == "align")
    app = choose(page(), plan_id=plan.plan_id)
    documents["cs-ms"][1]["notes"] += " revised synthetic notes"
    run(app)
    assert app.selectbox(key="chat_plan_id").value is None
    assert sum("方案有更新" in item.value for item in app.caption) == 1
    run(app)
    assert not any("方案有更新" in item.value for item in app.caption)
    app.chat_input[0].set_value("question after revision")
    run(app)
    assert "plan" not in backend.posts[-1]


def test_409_clears_selection_on_the_next_rerun_not_after_widget_creation(chat_page, monkeypatch):
    backend, documents, calls = chat_page
    plan = next(plan for plan in plans() if plan.pathway == "align")
    original = type(backend).__call__

    def transport(self, request):
        if request.method == "POST":
            self.posts.append(json.loads(request.content))
            return httpx.Response(409, json={"detail": "请在上方「方案版本（可选）」重新选择。"})
        return original(self, request)

    monkeypatch.setattr(type(backend), "__call__", transport)
    app = choose(page(), plan_id=plan.plan_id)
    app.chat_input[0].set_value("question")
    run(app)
    assert app.selectbox(key="chat_plan_id").value is None
    assert app.session_state["chat_plan_id"] is None
    assert len(backend.posts) == 1


def test_invalid_context_cannot_create_a_source_link_or_persist_in_history():
    from app.chat_plan_view import validated_plan_context
    from app.state_manager import add_message
    assert validated_plan_context({"source_url": "https://evil.test/"}) is None
    state = {"messages": []}
    add_message(state, role="assistant", content="old")
    assert set(state["messages"][0]) == {"role", "content", "evidence", "matched_via"}
    add_message(state, role="assistant", content="bad", plan_context={"source_url": "https://evil.test/"})
    assert "plan_context" not in state["messages"][-1]


def test_panel_treats_plan_labels_as_plain_text_and_keeps_open_pool_caveats():
    from app.chat_plan_view import render_plan_context
    from rag.answer_evidence import build_plan_context
    from schemas.course import Course
    from schemas.program_plan import ProgramPlan
    raw = plans()[5].model_dump()
    raw["concentration"] = "<b>unsafe</b> [x](https://evil.test/)"
    raw["requirements"]["label"] = "<b>root</b> [x](https://evil.test/)"
    plan = ProgramPlan.model_validate(raw)
    context = build_plan_context(plan, [Course(course_id="c-open", primary_code="CS 7180", primary_name="Synthetic")])

    class Surface:
        def __init__(self):
            self.captions, self.texts, self.markdowns = [], [], []
        def caption(self, text): self.captions.append(text)
        def text(self, text): self.texts.append(text)
        def markdown(self, text): self.markdowns.append(text)

    surface = Surface()
    render_plan_context(surface, context.model_dump(mode="json"))
    assert any("开放" in text and "核实" in text for text in surface.texts)
    assert any("不代表" in text for text in surface.captions)
    assert any("<b>root</b>" in text for text in surface.texts)
    assert not any("evil.test" in text for text in surface.markdowns)
    assert len(surface.markdowns) == 1 and plan.source_url in surface.markdowns[0]
