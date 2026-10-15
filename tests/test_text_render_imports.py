"""Pure-helper imports stay stdlib-only; exercise lazy callers in isolated fresh processes."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROBE = r'''
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, sys.argv[1])
mode = sys.argv[2]
before = set(sys.modules)
if mode == "pure":
    import app.text_render as text
    assert Path(text.__file__).resolve().parent == Path(sys.argv[1]) / "app"
    assert text.literal_markdown("<name>") == r"\<name\>"
    assert text._one_line("a\nb") == "a b"
    assert text.plain_text_html("<a>\nb") == "&lt;a&gt;<br>b"
    assert text.labelled_line_html("x", "<b>") == (
        '<div class="nc-line"><span class="nc-line-label">x：</span>&lt;b&gt;</div>')
    added = set(sys.modules) - before
    unexpected = sorted(name for name in added if name not in {"app", "app.text_render"}
                        and name.split(".")[0] not in sys.stdlib_module_names)
    assert not unexpected, f"Unexpected non-stdlib helper dependencies: {unexpected}"
elif mode == "theme-prerequisite":
    from app.ui_theme import prereq_label_md
    assert "CS 5004" in prereq_label_md(
        code="CS 5004", name="Synthetic name", course_id="c", requirement="prerequisite")
else:
    class FakeSt:
        def __init__(self):
            self.session_state = {}
            self.shown = []
        def info(self, text):
            self.shown.append(text)
        warning = info
        caption = info
        def markdown(self, text, **kwargs):
            self.shown.append(text)
        def button(self, *args, **kwargs):
            return False
        def expander(self, *args, **kwargs):
            return self
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            return False
        def code(self, *args, **kwargs):
            pass

    if mode == "scope":
        from app.program_plan_view import scope_label
        plan = SimpleNamespace(campus="boston", catalog_year="2026-2027", pathway="standard",
                               concentration="Synthetic <c> *concentration*")
        shown = scope_label(plan, markdown=True)
    elif mode == "deep":
        import app.api_client as api
        from app.deep_links import _apply_course_ref
        class FakeClient:
            def __init__(self, **kwargs):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *exc):
                return False
            def resolve_course(self, ref):
                return {"matches": [{"course_id": "c1", "primary_code": "CS 1 <c>"},
                                    {"course_id": "c2", "primary_code": "CS 2 *concentration*"}]}
        api.ApiClient = FakeClient
        st = FakeSt()
        assert _apply_course_ref(st, "synthetic", pages=["search", "programs"])
        shown = st.shown[-1]
    else:
        assert mode == "curriculum"
        import app.program_view as view
        import app.program_plan_view as plans
        st = FakeSt()
        view.get_curriculum_cached = lambda *args: {
            "prefix": "Synthetic", "full_name": "Synthetic program",
            "notes": "Synthetic <c> *concentration*", "plans": [], "semesters": []}
        plans.render_program_plans = lambda *args, **kwargs: None
        view._render_curriculum(st, "synthetic")
        shown = "\n".join(st.shown)
    assert r"\<c\>" in shown and r"\*concentration\*" in shown, shown

banned = ["rag", "faiss", "app.answer_evidence_view"]
if mode in ("pure", "theme-prerequisite"):
    banned += ["numpy", "torch", "streamlit", "schemas", "pydantic"]
unexpected = sorted(name for name in sys.modules
                    if any(name == prefix or name.startswith(prefix + ".") for prefix in banned))
assert not unexpected, f"Unexpected modules after {mode} call: {unexpected}"
print("OK")
'''


@pytest.mark.parametrize("mode", ["pure", "theme-prerequisite", "deep", "scope", "curriculum"])
def test_fresh_process_does_not_load_evidence_or_rag_dependencies(mode):
    result = subprocess.run([sys.executable, "-I", "-B", "-c", PROBE, str(ROOT), mode],
                            capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "OK"


def test_original_helper_imports_are_compatible_aliases():
    from app import answer_evidence_view, text_render, ui_theme

    assert answer_evidence_view.literal_markdown is text_render.literal_markdown
    assert answer_evidence_view.WORD_JOINER is text_render.WORD_JOINER
    assert answer_evidence_view._URL_START is text_render._URL_START
    assert ui_theme._one_line is text_render._one_line
    assert ui_theme.plain_text_html is text_render.plain_text_html
    assert ui_theme.labelled_line_html is text_render.labelled_line_html
    # Identity can accidentally hold for interned literals/cached regexes; forbid local copies too.
    tree = ast.parse(Path(answer_evidence_view.__file__).read_text(encoding="utf-8"))
    assigned = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)}
    assert not assigned.intersection({"WORD_JOINER", "_URL_START"})


def test_all_app_literal_imports_use_the_pure_seam():
    callers = set()
    for path in (ROOT / "app").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and any(alias.name == "literal_markdown" for alias in node.names):
                assert node.module == "app.text_render", (path.name, node.lineno, node.module)
                callers.add(path.name)
    assert {"answer_evidence_view.py", "deep_links.py", "program_plan_view.py",
            "program_view.py", "ui_theme.py"} <= callers
