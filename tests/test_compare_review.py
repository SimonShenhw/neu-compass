"""Tests added after the G review (A20, B20, 2026-10-19): per-column identity, whole caveat sentences in their own
rows, the error paths, field caveats next to their fields, malformed bodies and the reload button.
中文：G 评审（A20、B20，2026-10-19）之后补的测试：每列只放自己那门课的数据、整句提醒放在对应的行、错误路径、
字段提醒放在字段旁边、无法识别的返回内容，以及重新加载按钮。
"""

import pytest
from markdown_it import MarkdownIt

from app.compare_view import credit_range_note, requisite_summary
from app.text_render import literal_markdown
from schemas.catalog_credit_hours import CatalogCreditHours
from tests.page_layout_support import run
from tests.test_compare_view import BAD, ROWS, comparison, detail, make_backend, text
from tests.test_course_requisite_view import bundle, document

OWN = {"course_id": "c1", "course_code": "CS 5001", "course_name": "Synthetic 1"}
# Written out, not imported: a test that compares against the module's own constant cannot catch a changed sentence.
NO_RULES = "没有可用的年度规则；不表示没有先修或共修要求。"
SESSION_NOTE = "列表只保存在这个页面会话里；刷新浏览器、登录或退出以后要重新加入。"
ESTIMATE, PREREQ, TOPICS, GRADING, PROGRAM, MISSING, ACTIONS = 2, 3, 4, 5, 6, 7, 8  # Row blocks; 0 is the header.


@pytest.fixture
def backend(monkeypatch):
    return make_backend(monkeypatch)


def grid(app, columns):
    """The nine row blocks (header + eight fields), each as its list of column blocks."""
    blocks = [b for b in app.get("flex_container") if len(list(b.children.values())) == columns
              and all(child.type == "column" for child in b.children.values())]
    assert len(blocks) == 9
    return [list(block.children.values()) for block in blocks]


def shown(column):
    parts = [e.value for kind in ("markdown", "text", "caption", "error") for e in getattr(column, kind)]
    return "\n".join([*parts, *(b.label for b in column.button)])


def own_docs(*years_and_raw):
    return [document(year, raw=raw).model_copy(update=OWN) for year, raw in years_and_raw]


def test_every_cell_and_button_names_its_own_course_and_holds_its_own_values(backend):
    backend.courses["c1"].update(topics_covered=["Topic-One"], workload_hours_per_week=3, term="Spring 2027")
    backend.courses["c2"].update(topics_covered=["Topic-Two"], workload_hours_per_week=7)
    cells = grid(comparison(["c2", "c1"]), 2)
    for col, (code, topic, hours, term, credits) in enumerate([("CS 5002", "Topic-Two", 7, "Fall 2026", 2),
                                                               ("CS 5001", "Topic-One", 3, "Spring 2027", 1)]):
        header = shown(cells[0][col])
        assert code in header and f"Synthetic {code[-1]}" in header
        assert f'nc-meta-label">Term</span><span class="nc-meta-value">{term}<' in header
        assert f'nc-meta-label">Credits</span><span class="nc-meta-value">{credits}<' in header
        for row in range(1, 9):
            assert cells[row][col].markdown[0].value == f"**{ROWS[row - 1]}** · {code}"
        assert f"每周约 {hours} 小时" in shown(cells[ESTIMATE][col])
        other = "Topic-One" if topic == "Topic-Two" else "Topic-Two"
        assert topic in shown(cells[TOPICS][col]) and other not in shown(cells[TOPICS][col])
        assert [b.label for b in cells[ACTIONS][col].button] == [f"查看详情 · {code}", f"移出对比 · {code}"]


def test_a_course_code_is_data_in_every_label_and_button(backend):
    backend.courses["c1"]["primary_code"] = "CS *5001* [x](https://elsewhere.example)"
    cells = grid(comparison(["c1"]), 1)
    escaped = literal_markdown("CS *5001* [x](https://elsewhere.example)")
    assert escaped != "CS *5001* [x](https://elsewhere.example)"
    for row in range(1, 9):
        assert cells[row][0].markdown[0].value == f"**{ROWS[row - 1]}** · {escaped}"
    assert [b.label for b in cells[ACTIONS][0].button] == [f"查看详情 · {escaped}", f"移出对比 · {escaped}"]


def test_a_failed_column_names_its_course_in_the_error_and_every_cell(backend):
    backend.status["c2"] = 404
    app = comparison(["c1", "c2", "c3"])
    cells = grid(app, 3)
    error = cells[0][1].error[0].value
    assert error == literal_markdown("课程加载失败（c2）：" + BAD)
    tokens = [t.type for block in MarkdownIt("commonmark").parse(error) for t in (block.children or [])]
    assert not {"link_open", "image", "html_inline", "strong_open"} & set(tokens)
    for row in range(1, 8):
        assert cells[row][1].markdown[0].value == f"**{ROWS[row - 1]}** · c2"
        assert [e.value for e in cells[row][1].text] == ["加载失败"]
    assert [b.label for b in cells[ACTIONS][1].button] == ["移出对比 · c2"]
    assert "CS 5003" in shown(cells[0][2]) and cells[ESTIMATE][2].markdown[0].value.endswith("CS 5003")


def test_a_503_column_shows_the_fixed_text_not_the_exception(backend):
    backend.failed.add("c1")
    app = comparison(["c1"])
    assert [e.value for e in app.error] == ["课程加载失败（c1）：服务暂不可用，请稍后手动重试。"]


@pytest.mark.parametrize("status,body", [(200, None), (200, []), (204, None), (200, {"course_id": "c2"}),
    (200, {"course_id": "c2", "primary_code": 5002, "primary_name": "Synthetic 2"}),
    (200, {"course_id": "c2", "primary_code": "CS 5002", "primary_name": None}),
    (200, {"course_id": 2, "primary_code": "CS 5002", "primary_name": "Synthetic 2"})])
def test_an_unrecognised_body_fails_only_its_own_column(backend, status, body):
    backend.status["c2"] = status
    backend.courses["c2"] = body
    cells = grid(comparison(["c1", "c2", "c3"]), 3)
    assert [e.value for e in cells[0][1].error] == ["课程加载失败（c2）：服务返回了无法识别的内容。"]
    assert [b.label for b in cells[ACTIONS][1].button] == ["移出对比 · c2"]
    assert "CS 5001" in shown(cells[0][0]) and "CS 5003" in shown(cells[0][2])


def test_a_malformed_field_blanks_only_its_own_cell(backend):
    backend.courses["c1"]["grading_components"] = [{"name": "Exam", "weight": "half"}]
    cells = grid(comparison(["c1", "c2"]), 2)
    assert [e.value for e in cells[GRADING][0].text] == ["这一项的数据格式不对，没有显示。"]
    assert "CS 5002" in shown(cells[0][1]) and len(cells[ACTIONS][0].button) == 2
    assert "没有记录" in shown(cells[GRADING][1])


def test_reload_appears_only_with_a_failed_column_and_keeps_the_list(backend):
    app = comparison(["c1", "c2"])
    assert not any(b.key == "compare-reload" for b in app.button)
    backend.failed.add("c2")
    run(app)
    backend.failed.clear()
    backend.reads.clear()
    app.button(key="compare-reload").click()
    run(app)
    assert [cid for _, cid, _ in backend.reads] == ["c1", "c2"]
    assert not app.error and app.session_state["compare_course_ids"] == ["c1", "c2"]
    assert not any(b.key == "compare-reload" for b in app.button)


def test_the_page_says_the_list_lives_only_in_this_session_and_where_to_add(backend):
    assert SESSION_NOTE in [e.value for e in comparison(["c1"]).caption]
    assert "在「🔍 课程搜索」页打开一门课的详情，点 ➕ 加入对比，最多选择 4 门课。" in text(comparison())


def test_whole_caveat_sentences_sit_in_their_own_rows(backend):
    backend.courses["c1"].update(program_context=[{"program_name": "Synthetic MS", "requirement_type": "core"}])
    cells = grid(comparison(["c1"]), 1)
    assert [e.value for e in cells[ESTIMATE][0].caption] == ["来自学生评价的估计，不是官方信息；缺失不等于零或简单。"]
    assert "没有记录" in cells[ESTIMATE][0].markdown[1].value
    assert [e.value for e in cells[PREREQ][0].text] == [NO_RULES]
    assert [e.value for e in cells[TOPICS][0].text] == ["没有记录"]
    assert "没有记录" in cells[GRADING][0].markdown[1].value
    assert [e.value for e in cells[PROGRAM][0].caption] == ["旧 seed 关系，未核验；不是正式方案，不判断注册或毕业资格。"]
    assert [e.value for e in cells[MISSING][0].caption] == ["缺失不等于零、简单或无要求。"]


def test_without_evidence_the_catalog_row_does_not_claim_there_is_no_archive(backend):
    backend.courses["c1"].pop("answer_evidence")
    cells = grid(comparison(["c1"]), 1)
    assert [e.value for e in cells[1][0].text] == ["目录存档情况没有记录。"]


def test_capture_date_uses_the_detail_page_format(backend):
    backend.courses["c1"]["answer_evidence"]["catalog"] = {
        "course_code": "CS 5001", "course_name": "Synthetic 1", "description": "Synthetic description.",
        "catalog_url": "https://catalog.northeastern.edu/course-descriptions/cs/", "snapshot_id": "catalog:" + "a" * 64,
        "imported_at": "2026-10-01T00:00:00Z", "retrieved_at": "2026-09-30T02:00:00Z"}
    cells = grid(comparison(["c1"]), 1)
    assert "目录抓取：2026-09-30 02:00 UTC。" in [e.value for e in cells[1][0].text]


def test_requisite_tail_line_and_schema_warning_are_whole_sentences(backend):
    course = {**backend.courses["c1"], "course_requisites": bundle(*own_docs(("2026-2027", "CS 5010")),
              warnings=["structured_requisite_schema_unusable"])}
    lines = requisite_summary(course)
    assert lines[0] == "存在不可用记录或存储结构；不能据此确认完整要求。"
    assert lines[-1] == "未列出或未解析的条款仍未知；不判断个人适用年度或能否注册。"


@pytest.mark.parametrize("data,expected", [({"documents": ["bad"]}, "年度规则没有通过校验，暂不显示；不表示没有先修或共修要求。"),
    ({"schema_available": False}, "结构化先修规则暂时不可用；不表示没有先修或共修要求。")])
def test_unreadable_requisites_never_read_as_no_requirements(backend, data, expected):
    assert requisite_summary({**backend.courses["c1"], "course_requisites": data}) == [expected]


def test_three_years_where_only_the_middle_one_differs_are_not_called_the_same(backend):
    docs = own_docs(("2026-2027", "CS 5010"), ("2025-2026", "CS 5000"), ("2024-2025", "CS 5010"))
    lines = requisite_summary({**backend.courses["c1"], "course_requisites": bundle(*docs)})
    assert "这些年度已记录的条款不同，请按适用年度核对。" in lines


@pytest.mark.parametrize("update", [{"course_code": "CS 5999"}, {"course_name": "Other name"}])
def test_a_document_with_the_same_id_but_another_code_or_name_is_not_used(backend, update):
    doc = document().model_copy(update={**OWN, **update})
    lines = requisite_summary({**backend.courses["c1"], "course_requisites": bundle(doc)})
    assert lines == ["有课程身份不符的年度记录，未用于比较。", NO_RULES]


def test_field_caveats_sit_next_to_their_fields_and_the_overview_line_stays(backend):
    backend.courses["c1"]["answer_evidence"]["warnings"] = [
        "field_evidence_value_conflict", "topics_source_unavailable", "catalog_metadata_conflict",
        "synthetic_record_not_real_course"]
    backend.courses["c1"].update(workload_hours_per_week=12, topics_covered=["Graphs"])
    cells = grid(comparison(["c1", "c2"]), 2)
    assert "有估计值和评价原文对不上" in shown(cells[ESTIMATE][0])
    assert "主题列表没有来源" in shown(cells[TOPICS][0])
    assert "目录学分和课程记录不一致" in shown(cells[0][0]) and "这是测试数据" in shown(cells[0][0])
    assert "有估计值和评价原文对不上" in shown(cells[1][0])  # The description row keeps the full line.
    for row in (0, ESTIMATE, TOPICS):
        assert "⚠️" not in shown(cells[row][1])


def test_a_title_credit_range_is_named_under_the_header(backend):
    hours = CatalogCreditHours.from_text("1-4 Hours")
    newest, older = own_docs(("2026-2027", "CS 5010"), ("2025-2026", "CS 5010"))
    backend.courses["c1"]["course_requisites"] = bundle(newest.model_copy(update={"credit_hours": hours}), older)
    cells = grid(comparison(["c1"]), 1)
    assert (literal_markdown("2026-2027 目录标题学分：1-4 Hours；实际班次学分未声明。")
            in [e.value for e in cells[0][0].caption])
    fixed = newest.model_copy(update={"credit_hours": CatalogCreditHours.from_text("4 Hours")})
    assert credit_range_note({**backend.courses["c1"], "course_requisites": bundle(fixed)}) is None
    assert credit_range_note(backend.courses["c2"]) is None


def test_the_credit_note_ignores_other_courses_and_conflicting_years(backend):
    hours = {"credit_hours": CatalogCreditHours.from_text("1-4 Hours")}
    [own] = own_docs(("2025-2026", "CS 5010"))
    # A range on a document of another course, even a newer one, is not this course's range.
    # 中文：别的课的文档上写着范围学分，哪怕年份更新，也不是这门课的。
    foreign = document("2026-2027", raw="CS 5010").model_copy(update={**OWN, "course_code": "CS 5999", **hours})
    assert credit_range_note({**backend.courses["c1"], "course_requisites": bundle(foreign, own)}) is None
    # Two documents for the newest year: the prerequisite row says it did not pick one, so neither does the note.
    # 中文：最新年度有两份记录：先修那一行说没有任取一份，学分提示也不任取。
    first, second = own_docs(("2026-2027", "CS 5010"), ("2026-2027", "CS 5020"))
    listing = bundle(first.model_copy(update=hours), second)
    assert credit_range_note({**backend.courses["c1"], "course_requisites": listing}) is None
    assert requisite_summary({**backend.courses["c1"], "course_requisites": listing})[-1] == "同年度有冲突记录，未任取一份比较。"


def test_detail_caption_counts_the_list_not_the_position(backend):
    app = detail(backend, ["c5", "c1", "c2"])
    assert app.button(key="compare-add-c5").disabled
    assert "已在对比中（3/4）" in text(app)


def test_a_full_list_that_contains_the_course_says_already_not_full(backend):
    app = detail(backend, ["c1", "c2", "c5", "c3"])
    assert "已在对比中（4/4）" in text(app) and "先移出一门" not in text(app)
