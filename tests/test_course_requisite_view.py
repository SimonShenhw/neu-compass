"""Explicit choice, safe text and no qualification graph from old flat edges."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from streamlit.testing.v1 import AppTest

from app.course_requisite_view import legacy_graph_allowed, render_course_requisites, rule_lines
from schemas.course_requisite_document import CourseRequisiteDocument, CourseRequisiteListing
from scrapers.course_requisites import parse_clause


def document(year="2026-2027", raw="(CS 5001 with a minimum grade of B- or CS 5010 with a minimum grade of C- (Graduate)); DS 5110 (may be taken concurrently)"):
    return CourseRequisiteDocument(course_id="design", course_code="CS 5004", course_name="Design", catalog_year=year,
        source={"url": "https://catalog.northeastern.edu/course-descriptions/cs/", "catalog_year": year,
                "captured_at": datetime(2026, 10, 1, tzinfo=timezone.utc), "sha256": "c" * 64, "byte_count": 10, "page_title": "Computer Science (CS)"},
        requisites={"prerequisite": parse_clause(raw), "corequisite": parse_clause("CS 5005")})


def bundle(*documents, **fields):
    return CourseRequisiteListing(schema_available=True, has_any_stored_records=bool(documents), documents=list(documents), **fields).model_dump(mode="json")


class FakeSt:
    def __init__(self, choice=None):
        self.session_state, self.choice = {}, choice
        self.texts, self.markdowns, self.captions, self.warnings = [], [], [], []
    def text(self, text):
        self.texts.append(text)
    def markdown(self, text):
        self.markdowns.append(text)
    def caption(self, text):
        self.captions.append(text)
    def warning(self, text):
        self.warnings.append(text)
    def selectbox(self, label, options, **kwargs):
        assert self.choice in options
        return self.choice
    def expander(self, label):
        return self
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False


def render(st, data):
    render_course_requisites(st, data, course_id="design", course_code="CS 5004", course_name="Design", key="test-year")


def test_rule_lines_keep_nested_operators_grades_level_concurrency_and_corequisite():
    lines = "\n".join(rule_lines(document().requisites.prerequisite.rule))
    assert "全部分支（AND）" in lines and "任一分支（OR）" in lines
    assert "最低成绩：B-" in lines and "Graduate" in lines and "明示可并修" in lines
    assert rule_lines(document().requisites.corequisite.rule) == ["- CS 5005"]


def test_default_choice_is_none_and_does_not_show_any_edition_tree():
    st = FakeSt()
    render(st, bundle(document("2026-2027"), document("2025-2026")))
    assert st.texts == [] and not any("官方院系来源" in text for text in st.markdowns)


@pytest.mark.parametrize("data,allowed", [
    (None, True),
    ({"schema_available": False}, True),
    ({"schema_available": True, "documents": []}, True),
    ({"schema_available": True, "documents": [], "has_any_stored_records": True}, False),
    ({"schema_available": True, "documents": [], "unusable_records": 1}, False),
    ({"schema_available": True, "documents": [], "warnings": ["structured_requisite_schema_unusable"]}, False),
    ({"documents": [{"bad": "data"}]}, False),
    ("bad format", False),
])
def test_legacy_graph_fallback_depends_on_raw_state_not_usable_tree(data, allowed):
    assert legacy_graph_allowed(data) is allowed


def test_usable_and_unknown_documents_both_block_old_flat_graph():
    assert legacy_graph_allowed(bundle(document())) is False
    assert legacy_graph_allowed(bundle(document(raw=None))) is False
    assert legacy_graph_allowed(bundle(document(raw="permission of instructor"))) is False


def test_unknown_and_unparsed_raw_html_are_plain_text_not_markup_or_links():
    raw = '<img src="https://evil.test/x" onerror="alert(1)">'
    st = FakeSt("2026-2027")
    render(st, bundle(document(raw=raw)))
    assert raw in st.texts and any("未解析" in text for text in st.texts)
    assert all("evil.test" not in text for text in st.markdowns)
    missing = FakeSt("2026-2027")
    render(missing, bundle(document(raw=None)))
    assert any("未列出" in text and "不是" in text for text in missing.texts)


def test_bad_source_and_course_identity_are_not_exposed_as_evidence_links():
    data = bundle(document())
    data["documents"][0]["source"]["url"] = "https://evil.test/"
    st = FakeSt("2026-2027")
    render(st, data)
    assert st.warnings and all("evil.test" not in text for text in st.markdowns)
    data = bundle(document())
    data["documents"][0]["course_id"] = "another-course"
    st = FakeSt("2026-2027")
    render(st, data)
    assert st.warnings and st.texts == [] and not legacy_graph_allowed(data)


def test_duplicate_edition_is_not_first_match_and_old_selected_year_is_cleared():
    st = FakeSt()
    render(st, bundle(document(), document()))
    assert st.warnings and st.texts == []
    st = FakeSt()
    st.session_state["test-year"] = "2024-2025"
    render(st, bundle(document()))
    assert "test-year" not in st.session_state


def app_source(data):
    return f'''
import json
import streamlit as st
from app.course_requisite_view import render_course_requisites, legacy_graph_allowed
data = json.loads({json.dumps(data)!r})
render_course_requisites(st, data, course_id="design", course_code="CS 5004", course_name="Design", key="year")
if legacy_graph_allowed(data):
    st.graphviz_chart("digraph {{ A -> B }}")
'''


def test_real_widget_explicit_selection_and_clear_preserve_and_or_and_no_legacy_graph():
    app = AppTest.from_string(app_source(bundle(document(), document("2025-2026", "CS 5010")))).run(timeout=45)
    assert not app.exception and app.selectbox[0].value is None and len(app.text) == 0
    assert len(app.get("graphviz_chart")) == 0
    app.selectbox[0].set_value("2026-2027").run(timeout=45)
    assert not app.exception
    text = "\n".join(item.value for item in app.text)
    assert "全部分支（AND）" in text and "任一分支（OR）" in text and "B-" in text and "明示可并修" in text
    assert "CS 5005" in text and any("共修" in item.value for item in app.markdown)
    assert any("校区或个人路径" in item.value for item in app.caption)
    app.selectbox[0].set_value("2025-2026").run(timeout=45)
    assert not app.exception and not any("最低成绩：B-" in item.value for item in app.text)
    app.selectbox[0].set_value(None).run(timeout=45)
    assert not app.exception and len(app.text) == 0 and len(app.get("graphviz_chart")) == 0


def test_real_widget_unparsed_clause_is_visible_without_partial_rule_or_markup():
    raw = "CS 5001 or permission of instructor <script>bad()</script>"
    app = AppTest.from_string(app_source(bundle(document(raw=raw)))).run(timeout=45)
    app.selectbox[0].set_value("2026-2027").run(timeout=45)
    assert not app.exception
    assert any(item.value == raw for item in app.text)
    assert not any(raw in item.value for item in app.markdown)
    assert any("未解析" in item.value for item in app.text)
    assert len(app.get("graphviz_chart")) == 0
