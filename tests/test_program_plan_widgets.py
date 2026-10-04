"""Real Streamlit widgets exercised headlessly; no browser, API or OAuth calls."""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

# Mounted-workspace/cold startup can exceed 20s in the full suite. These are
# functional assertions, not a latency benchmark; keep a bounded test budget.
WIDGET_TIMEOUT = 45


def test_real_scoped_selector_defaults_to_none_then_renders_selected_rule_tree():
    app = AppTest.from_string('''
import json
from pathlib import Path
import streamlit as st
import app.program_plan_view as view
root = Path(view.__file__).resolve().parent.parent
documents = json.loads((root / "data/program_plan_seed/boston_2026_2027_core_fragments.json").read_text(encoding="utf-8"))
view.render_program_plans(st, documents, key="scoped-plan")
''').run(timeout=WIDGET_TIMEOUT)
    assert len(app.exception) == 0
    assert app.selectbox[0].value is None
    assert len(app.text) == 0
    app.selectbox[0].set_value("ds-ms-boston-2026-2027-standard").run(timeout=WIDGET_TIMEOUT)
    assert len(app.exception) == 0
    assert any("仅规则片段" in item.value for item in app.caption)
    assert any("任一分支（OR）" in item.value and "EECE 7205" in item.value for item in app.text)


def test_real_chat_family_selector_can_be_selected_and_cleared():
    app = AppTest.from_string('''
import streamlit as st
from app.program_plan_view import render_chat_program_selector
selected = render_chat_program_selector(st, [
    {"program_id": "cs-ms", "full_name": "CS MS"},
    {"program_id": "cs-align", "full_name": "CS Align"},
])
st.text(f"Selected: {selected}")
''').run(timeout=WIDGET_TIMEOUT)
    assert len(app.exception) == 0 and app.selectbox[0].value is None
    app.selectbox[0].set_value("cs-align").run(timeout=WIDGET_TIMEOUT)
    assert len(app.exception) == 0
    assert app.text[0].value == "Selected: cs-align"
    app.selectbox[0].set_value(None).run(timeout=WIDGET_TIMEOUT)
    assert len(app.exception) == 0 and app.text[0].value == "Selected: None"


def test_real_extended_info_rules_keep_optional_exit_and_excluded_candidates_visible():
    app = AppTest.from_string('''
import json
from pathlib import Path
import streamlit as st
import app.program_plan_view as view
root = Path(view.__file__).resolve().parent.parent
documents = json.loads((root / "data/program_plan_seed/boston_2026_2027_extended_rules.json").read_text(encoding="utf-8"))
view.render_program_plans(st, documents, key="extended-plan")
''').run(timeout=WIDGET_TIMEOUT)
    assert len(app.exception) == 0 and app.selectbox[0].value is None
    app.selectbox[0].set_value("info-ms-boston-2026-2027-standard-general").run(timeout=WIDGET_TIMEOUT)
    assert len(app.exception) == 0
    text = "\n".join(item.value for item in app.text)
    assert "任一分支（OR）" in text and "Thesis Option" in text and "Coursework Option" in text
    assert "排除：CSYE 6220、INFO 5200" in text and "可选分支" in text
    assert "来源 HTML 字节摘要" in text
