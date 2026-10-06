"""Course detail panel: student-first order, provenance folded, extracted fields as plain text.

中文：课程详情面板：学生关心的内容在前、来源信息折叠、抽取字段按纯文本显示。
"""

from __future__ import annotations

from markdown_it import MarkdownIt

from app.course_detail_view import grading_text, render_course_detail, soft_estimates
from db.catalog_source_repository import CatalogSourceRepository
from rag.answer_evidence import course_answer_evidence
from schemas.course import Course
from scrapers.neu_catalog import CatalogEntry
from tests.ui_recorder import Recorder

# Ordinary Markdown in a data value: must stay literal text in the panel.
LINKED = "[note](https://elsewhere.example/page) **bold**"
COMMONMARK = MarkdownIt("commonmark")


def payload(**updates) -> dict:
    record = Course(course_id="neu-cs-5800", primary_code="CS 5800", primary_name="Algorithms",
                    source_review_ids=["rmp_review_a"])
    snapshot = CatalogSourceRepository.snapshot(CatalogEntry(
        course_code="CS 5800", course_name="Algorithms", description="Graph algorithms and dynamic programming.",
        catalog_url="https://catalog.northeastern.edu/course-descriptions/cs/",
    ))
    data = {
        "course_id": "neu-cs-5800", "primary_code": "CS 5800", "primary_name": "Algorithms", "credits": 4,
        "answer_evidence": course_answer_evidence(record, snapshot).model_dump(mode="json"),
        "workload_hours_per_week": 12.0, "difficulty_score": 4.0,
        "course_requisites": None, "prerequisites": [],
        "grading_components": [{"name": "Exams " + LINKED, "weight": 0.5}, {"name": "Homework", "weight": None}],
        "topics_covered": ["graphs"], "skill_tags": ["proofs"],
        "career_relevance": ["software " + LINKED], "professor": ["Ada " + LINKED],
        "ai_policy": {"permitted_tools": ["Copilot " + LINKED], "banned_tools": [], "disclosure_required": True,
                      "notes": "first line\n\nsecond line " + LINKED},
        "evidence_snippets": [{"field": "workload_hours_per_week", "value": 12, "source_id": "rmp_review_a",
                               "quote": "About 12 hours a week", "confidence": 0.8}],
    }
    data.update(updates)
    return data


def index(log, predicate) -> int:
    return next(i for i, entry in enumerate(log) if predicate(entry))


def test_description_estimates_and_prerequisites_come_before_the_folded_sources():
    st = Recorder()
    render_course_detail(st, payload(), cid="neu-cs-5800")
    log = st.log
    top = [entry for entry in log if entry[2] == ()]
    description = index(log, lambda e: e[0] == "text" and e[1].startswith("Graph algorithms"))
    estimates = index(log, lambda e: e[0] == "markdown" and "学生评价里的估计" in e[1])
    prerequisites = index(log, lambda e: e[1] == "**🧩 先修要求**")
    sources = index(log, lambda e: e[0] == "expander" and e[1].startswith("📎 来源与说明"))
    share = index(log, lambda e: e[0] == "expander" and e[1] == "🔗 分享这门课")
    assert 0 < description < estimates < prerequisites < sources < share
    assert top[0][0] == "markdown" and "CS 5800" in top[0][1]  # Header first.
    assert log[description][2] == () and log[estimates][2] == ()
    # The description shows once, at the top; the folded provenance does not repeat it.
    assert sum(1 for e in log if e[0] == "text" and e[1].startswith("Graph algorithms")) == 1
    folded = [e for e in log if e[2][:1] == (log[sources][1],)]
    assert any(e[0] == "markdown" and e[1].startswith("[官方目录来源](") for e in folded)
    assert any(e[0] == "caption" and e[1].startswith("快照：") for e in folded)
    assert any(e[0] == "caption" and e[1].startswith("记录来源") for e in folded)
    # Raw source IDs one more level down, inside the sources expander.
    assert any(e[0] == "text" and e[1] == "rmp_review_a" and len(e[2]) == 2 for e in folded)
    assert any(e[1] == "**评价和大纲原文摘录（1 条）**" for e in folded)
    assert not any(e[2] == () and e[0] == "caption" and e[1].startswith("快照：") for e in log)


def test_extracted_fields_render_as_one_escaped_html_block_never_markdown():
    """Name, topics, skills, instructors, grading names, careers and AI-policy text can come from
    an LLM reading reviews and syllabi. A CommonMark parser must see each line as a single HTML
    block (a blank line inside a value would end it): no link, no emphasis."""
    st = Recorder()
    render_course_detail(st, payload(primary_name="Algorithms\n\n" + LINKED, topics_covered=["graphs\n\n" + LINKED],
                                     skill_tags=["proofs\r\n\r\n" + LINKED]), cid="neu-cs-5800")
    lines = [e[1] for e in st.log if e[0] == "markdown" and "elsewhere.example" in e[1]]
    assert len(lines) == 8  # Header, grading, topics, skills, careers, instructors, permitted tools, notes.
    for line in lines:
        assert line.startswith("<div") and "\n" not in line and "\r" not in line
        assert [token.type for token in COMMONMARK.parse(line)] == ["html_block"]
        assert line in st.html  # Without unsafe_allow_html the escaped markup would show literally.
    notes = next(line for line in lines if "first line" in line)
    assert "first line<br><br>second line" in notes  # A blank line would have ended the HTML block.
    assert not any(e[0] in {"caption", "markdown"} and "elsewhere.example" in e[1] and not e[1].startswith("<div")
                   for e in st.log)


def test_panel_without_optional_fields_still_renders_header_overview_and_sources():
    st = Recorder()
    render_course_detail(st, payload(workload_hours_per_week=None, difficulty_score=None, grading_components=[],
                                     topics_covered=[], skill_tags=[], career_relevance=[], professor=[],
                                     ai_policy=None, evidence_snippets=[], answer_evidence=None),
                         cid="neu-cs-5800")
    kinds = [(e[0], e[1]) for e in st.log if e[2] == ()]
    assert kinds[0][0] == "markdown" and "CS 5800" in kinds[0][1]
    assert not any("学生评价里的估计" in str(value) for _, value in kinds)
    assert any(kind == "expander" and value.startswith("📎 来源与说明") for kind, value in kinds)
    assert not any(kind == "expander" and value == "🤖 AI 使用政策" for kind, value in kinds)


def test_estimate_and_grading_text():
    assert soft_estimates({"workload_hours_per_week": 12.5, "difficulty_score": 4.0}) == "⏱️ 每周约 12.5 小时 · 🎚️ 难度 4/5"
    assert soft_estimates({"workload_hours_per_week": 0.0}) == "⏱️ 每周约 0 小时"  # Zero is a value, not missing.
    assert soft_estimates({}) is None
    assert grading_text([{"name": "Exams", "weight": 0.5}, {"name": "Lab", "weight": None}]) == "Exams 50% · Lab"
