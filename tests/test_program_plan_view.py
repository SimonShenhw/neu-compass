"""Rule/scope rendering and explicit selectors without a real browser."""

from __future__ import annotations

import json
from pathlib import Path

from app.program_plan_view import render_chat_program_selector, render_program_plans, rule_lines
from app.program_view import _semester_heading
from schemas.program_plan import RequirementNode

ROOT = Path(__file__).resolve().parent.parent


def document():
    return json.loads((ROOT / "data/program_plan_seed/boston_2026_2027_core_fragments.json").read_text(encoding="utf-8"))[1]


class FakeSurface:
    def __init__(self, choice=None):
        self.choice = choice
        self.captions, self.texts, self.markdowns, self.selectors, self.helps = [], [], [], [], []
        self.session_state = {}

    def caption(self, text):
        self.captions.append(text)

    def text(self, text):
        self.texts.append(text)

    def markdown(self, text):
        self.markdowns.append(text)

    def selectbox(self, label, values, *, format_func, key, help=None):
        self.selectors.append((label, values, [format_func(value) for value in values], key))
        self.helps.append(help)
        return self.choice

    def expander(self, label):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_no_document_legacy_scope_is_unknown():
    st = FakeSurface()
    render_program_plans(st, [], key="view")
    assert "旧 seed 的校区、目录年度和路径未知" in st.captions[0]


def test_selector_starts_with_none_and_never_auto_chooses_latest():
    st = FakeSurface()
    render_program_plans(st, [document()], key="view")
    assert st.selectors[0][1][0] is None
    assert "不默认最新版本" in st.selectors[0][2][0]
    assert st.texts == st.markdowns == []


def test_selected_partial_rules_scope_and_or_are_kept_explicit():
    data = document()
    st = FakeSurface(choice=data["plan_id"])
    render_program_plans(st, [data], key="view")
    assert any("boston" in line and "2026-2027" in line and "普通 MS" in line for line in st.captions)
    assert any("仅规则片段，不是完整培养方案" in line for line in st.captions)
    assert any("不判断注册或毕业资格" in line for line in st.captions)
    assert any("任一分支（OR）" in text and "EECE 7205" in text for text in st.texts)
    assert st.markdowns == [f"[官方目录来源]({data['source_url']})"]


def test_invalid_history_document_has_no_source_link():
    data = document()
    data["source_url"] = "javascript:bad"
    st = FakeSurface(choice=data["plan_id"])
    render_program_plans(st, [data], key="view")
    assert st.markdowns == [] and st.selectors == []
    assert any("校验未通过" in line for line in st.captions)


def test_rule_labels_and_source_ids_render_as_text_not_injected_markdown():
    data = document()
    data["notes"] = "[untrusted](https://evil.test)"
    data["requirements"]["label"] = "<script>bad</script>"
    st = FakeSurface(choice=data["plan_id"])
    render_program_plans(st, [data], key="view")
    assert data["notes"] in st.texts
    assert any("<script>bad</script>" in text for text in st.texts)
    assert all("evil.test" not in text for text in st.markdowns)


def test_selection_groups_are_not_displayed_as_all_courses_required():
    rule = RequirementNode(kind="select", label="Pool", course_codes=["CS 5100", "CS 5500", "CS 5800"],
        min_courses=3, min_credits=12, min_areas=2, areas={"a": ["CS 5100"], "b": ["CS 5500", "CS 5800"]})
    text = "\n".join(rule_lines(rule))
    assert "至少 3 门" in text and "至少 12 学分" in text and "至少 2 个领域" in text
    assert "不是所有候选均必修" in text


def test_unknown_semester_is_not_permission_to_enroll_anytime():
    assert _semester_heading(None).startswith("未提供推荐学期")
    assert "不等于任意学期都可修" in _semester_heading(None)
    assert "未核验" in _semester_heading(1)


def test_chat_program_choice_is_optional_and_does_not_imply_year_or_campus():
    programs = [{"program_id": "cs-ms", "full_name": "CS MS"}, {"program_id": "cs-align", "full_name": "CS Align"}]
    st = FakeSurface()
    assert render_chat_program_selector(st, programs) is None
    assert st.selectors[0][1][0] is None and st.selectors[0][2][0] == "不指定"
    assert st.selectors[0][0] == "你的项目（可选）"
    assert "不替你选校区或 Catalog 年份" in st.helps[0]
    selected = FakeSurface(choice="cs-align")
    assert render_chat_program_selector(selected, programs) == "cs-align"
    assert any("校区、Catalog 年份和你个人的要求仍需要自己核实" in line for line in selected.captions)


def test_stale_chat_selection_is_cleared_before_rendering_widget():
    st = FakeSurface()
    st.session_state["chat_program_id"] = "deleted"
    render_chat_program_selector(st, [{"program_id": "cs-ms", "full_name": "CS"}])
    assert "chat_program_id" not in st.session_state
