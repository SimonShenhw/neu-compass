"""The new helper seam is genuinely stdlib-only, with legacy import paths intact."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("mode", ["pure", "theme-prerequisite"])
def test_fresh_process_does_not_load_ui_rag_or_schema_dependencies(mode):
    code = '''import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
if sys.argv[2] == "pure":
    import app.text_render as text
    assert Path(text.__file__).resolve().parent == Path(sys.argv[1]) / "app"
    assert text.literal_markdown("<name>") == r"\\<name\\>"
else:
    from app.ui_theme import prereq_label_md
    assert "CS 5004" in prereq_label_md(code="CS 5004", name="Synthetic name", course_id="c", requirement="prerequisite")
banned = ["rag", "faiss", "numpy", "torch", "streamlit", "schemas", "pydantic", "app.answer_evidence_view"]
if sys.argv[2] == "pure":
    banned.append("app.ui_theme")
assert not [name for name in sys.modules if any(name == prefix or name.startswith(prefix + ".") for prefix in banned)]
print("OK")
'''
    result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(ROOT), mode],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "OK"


def test_original_helper_imports_are_compatible_aliases():
    from app import answer_evidence_view, text_render, ui_theme

    assert answer_evidence_view.literal_markdown is text_render.literal_markdown
    assert ui_theme._one_line is text_render._one_line
    assert ui_theme.plain_text_html is text_render.plain_text_html
    assert ui_theme.labelled_line_html is text_render.labelled_line_html


@pytest.mark.parametrize("relative", ["deep_links.py", "program_plan_view.py", "program_view.py", "ui_theme.py"])
def test_escaping_only_imports_do_not_pull_in_the_evidence_panel(relative):
    tree = ast.parse((ROOT / "app" / relative).read_text(encoding="utf-8"))
    imports = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
               and any(alias.name == "literal_markdown" for alias in node.names)]
    assert len(imports) == 1
    assert imports[0].module == "app.text_render"
