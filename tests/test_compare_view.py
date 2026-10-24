"""Offline comparison AppTest: guarded HTTP, literal data and row-aligned layout."""

import copy

import httpx
import pytest
from markdown_it import MarkdownIt
from streamlit.testing.v1 import AppTest

from tests.page_layout_support import SCRIPT, install_backend, run
from tests.test_course_requisite_view import bundle, document

SEARCH, PROGRAMS, COOP, COMPARE = "🔍 课程搜索 · Search", "🎓 培养方案 · Programs", "💼 Co-op 经验", "⚖️ 课程对比 · Compare"
BAD = '<b>unsafe</b> [x](https://elsewhere.example)\n\n**bold**'
ROWS = ["官方目录描述", "学生评价里的估计", "先修／共修", "主题", "考核构成", "在培养方案里的位置", "缺的数据", "操作"]


def make_backend(monkeypatch):
    """Five synthetic courses behind the guarded transport; `failed` answers 503, `status` any other code."""
    base = install_backend(monkeypatch)
    original = httpx.Client.send
    base.courses = {}
    for i in range(1, 6):
        base.courses[f"c{i}"] = {"course_id": f"c{i}", "primary_code": f"CS {5000 + i}",
            "primary_name": f"Synthetic {i}", "credits": i, "term": "Fall 2026", "delivery_mode": "in_person",
            "answer_evidence": {"catalog": None, "missing_fields": ["professor", "skill_tags"], "warnings": []}}
    base.failed = set()
    base.status = {}
    base.reads = []

    def send(client, request, **kwargs):
        assert isinstance(client._transport, httpx.MockTransport), "Live HTTP forbidden"
        if request.url.path.startswith("/course/c"):
            cid = request.url.path.rsplit("/", 1)[1]
            base.reads.append((request.method, cid, request.headers.get("authorization")))
            status = base.status.get(cid, 503 if cid in base.failed else 200)
            if status == 204:
                return httpx.Response(204, request=request)
            if status == 200 and base.courses[cid] is None:  # A JSON null body; json=None would send no body.
                return httpx.Response(200, content=b"null", headers={"content-type": "application/json"}, request=request)
            return httpx.Response(status, json={"detail": BAD} if status != 200 else base.courses[cid], request=request)
        return original(client, request, **kwargs)

    monkeypatch.setattr(httpx.Client, "send", send)
    return base


@pytest.fixture
def backend(monkeypatch):
    return make_backend(monkeypatch)


def comparison(ids=(), *, token=None):
    app = AppTest.from_string(SCRIPT)
    app.session_state["nav_page"] = COMPARE
    app.session_state["compare_course_ids"] = list(ids)
    if token:
        app.session_state["session_token"] = token
        app.session_state["user_id"] = "synthetic"
    return run(app)


def text(app):
    return "\n".join(e.value for kind in [app.markdown, app.text, app.caption, app.info, app.error] for e in kind)


def test_empty_page_navigation_order_footer_and_no_search_or_fetch(backend):
    app = comparison()
    # Batch T appended the privacy page; the first four keep their places. 中文：T 批在末尾加了隐私页，前四个位置不变。
    assert app.radio(key="nav_page").options == [SEARCH, PROGRAMS, COOP, COMPARE, "🔒 数据与隐私 · Privacy"]
    assert "打开一门课的详情，点 ➕ 加入对比" in text(app)
    assert not app.chat_input and not backend.reads and not backend.posts
    assert "nc-footer" in text(app)


@pytest.mark.parametrize("ids", [("c2",), ("c2", "c1"), ("c4", "c2", "c3", "c1")])
def test_one_two_four_columns_keep_order_and_fetch_once_per_run(backend, ids):
    app = comparison(ids, token="synthetic-token")
    assert backend.reads == [("GET", cid, "Bearer synthetic-token") for cid in ids]
    assert [b.key for b in app.button if str(b.key).startswith("compare-view-")] == [f"compare-view-{cid}" for cid in ids]
    assert not backend.posts and not app.chat_input
    backend.reads.clear()
    run(app)
    assert backend.reads == [("GET", cid, "Bearer synthetic-token") for cid in ids]
    # Each field has its own horizontal block; variable-height cells cannot shift later fields.
    row_blocks = [b for b in app.get("flex_container") if len(list(b.children.values())) == len(ids)
                  and all(child.type == "column" for child in b.children.values())]
    assert len(row_blocks) == 9
    first_code = backend.courses[ids[0]]["primary_code"]
    assert [next(iter(b.children.values())).markdown[0].value for b in row_blocks[1:]] == [f"**{r}** · {first_code}" for r in ROWS]
    for block in row_blocks:
        assert len(block.children) == len(ids)


def test_failed_middle_course_is_removable_and_others_still_render(backend):
    backend.failed.add("c2")
    app = comparison(["c1", "c2", "c3"])
    assert len(backend.reads) == 3 and len(app.error) == 1
    assert "Synthetic 1" in text(app) and "Synthetic 3" in text(app)
    assert not any(b.key == "compare-view-c2" for b in app.button)
    assert "先修" in text(app) and "没有记录" in text(app)
    backend.reads.clear()
    app.button(key="compare-remove-c2").click()
    run(app)
    assert app.session_state["compare_course_ids"] == ["c1", "c3"]
    assert [cid for _, cid, _ in backend.reads] == ["c1", "c3"]
    assert not app.error


def test_clear_list_does_not_clear_conversation_or_fetch_again(backend):
    app = comparison(["c1", "c2"])
    app.session_state["messages"] = [{"role": "user", "content": "keep"}]
    backend.reads.clear()
    app.button(key="compare-clear").click()
    run(app)
    assert app.session_state["compare_course_ids"] == [] and not backend.reads
    assert app.session_state["messages"] == [{"role": "user", "content": "keep"}]


def test_view_detail_navigates_to_search_without_chat_or_list_changes(backend):
    app = comparison(["c2", "c1"])
    backend.reads.clear()
    app.button(key="compare-view-c1").click()
    run(app)
    assert app.radio(key="nav_page").value == SEARCH
    assert app.session_state["selected_course_id"] == "c1"
    assert app.session_state["compare_course_ids"] == ["c2", "c1"]
    assert backend.reads == [("GET", "c1", None)] and not backend.posts
    assert "Synthetic 1" in text(app) and len(app.chat_input) == 1


def detail(backend, ids=()):
    app = AppTest.from_string(SCRIPT)
    app.session_state["selected_course_id"] = "c5"
    app.session_state["compare_course_ids"] = list(ids)
    return run(app)


def test_add_from_detail_shows_count_and_never_adds_twice(backend):
    app = detail(backend)
    app.button(key="compare-add-c5").click()
    run(app)
    assert app.session_state["compare_course_ids"] == ["c5"]
    assert app.button(key="compare-add-c5").disabled
    assert "已在对比中（1/4）" in text(app)
    run(app)
    assert app.session_state["compare_course_ids"] == ["c5"] and not backend.posts


def test_full_then_remove_then_add_from_detail(backend):
    app = detail(backend, ["c1", "c2", "c3", "c4"])
    assert app.button(key="compare-add-c5").disabled
    assert "先移出一门" in text(app)
    app.radio(key="nav_page").set_value(COMPARE)
    run(app)
    app.button(key="compare-remove-c2").click()
    run(app)
    app.radio(key="nav_page").set_value(SEARCH)
    run(app)
    assert not app.button(key="compare-add-c5").disabled
    app.button(key="compare-add-c5").click()
    run(app)
    assert app.session_state["compare_course_ids"] == ["c1", "c3", "c4", "c5"]


def test_estimates_missing_zero_values_and_unverified_program_caveat(backend):
    backend.courses["c1"].update(workload_hours_per_week=0, difficulty_score=0,
        program_context=[{"program_name": "Synthetic MS", "requirement_type": "core"}])
    app = comparison(["c1", "c2"])
    shown = text(app)
    assert "每周约 0 小时" in shown and "难度 0/5" in shown
    assert "学生评价里的估计" in shown and "不是官方" in shown
    assert "未核验" in shown and "不判断" in shown
    assert "教师、技能标签" in shown and "缺失不等于零" in shown


def test_untrusted_fields_are_html_escaped_or_text_never_source_markdown(backend):
    backend.courses["c1"].update(primary_name=BAD, topics_covered=[BAD],
        grading_components=[{"name": BAD, "weight": 0.5}],
        program_context=[{"program_name": BAD, "requirement_type": "core"}])
    backend.courses["c1"]["answer_evidence"]["missing_fields"] = [BAD]
    app = comparison(["c1", "c2"])
    blocks = [e for e in app.markdown if "elsewhere.example" in e.value]
    assert len(blocks) == 5
    parser = MarkdownIt("commonmark")
    for item in blocks:
        assert "<b>unsafe</b>" not in item.value and "&lt;b&gt;unsafe&lt;/b&gt;" in item.value
        assert item.proto.allow_html and [t.type for t in parser.parse(item.value)] == ["html_block"]
    assert not any("elsewhere.example" in e.value for e in app.caption)


@pytest.mark.parametrize("snapshot,expected", [(None, "没有官方目录描述的存档"),
    ({"catalog_url": "https://evil.example"}, "没有通过格式或来源校验"),
    ({"course_code": "CS 5001", "course_name": "Synthetic 1", "description": BAD,
      "catalog_url": "https://catalog.northeastern.edu/course-descriptions/cs/", "snapshot_id": "catalog:" + "a" * 64,
      "imported_at": "2026-10-01T00:00:00Z", "retrieved_at": "2026-09-30T02:00:00Z"}, "2026-09-30")])
def test_catalog_archive_and_capture_date_are_not_live_facts(backend, snapshot, expected):
    backend.courses["c1"]["answer_evidence"]["catalog"] = copy.deepcopy(snapshot)
    app = comparison(["c1"])
    assert expected in text(app)
    if snapshot and snapshot.get("description"):
        assert BAD in [e.value for e in app.text]
        assert "不是实时" in text(app)


@pytest.mark.parametrize("kind,expected", [("none", "没有可用的年度规则"), ("unavailable", "暂时不可用"),
    ("bad", "没有通过校验"),("same", "条款结构相同"), ("different", "条款不同"),
    ("one", "只记录了一个年度"), ("foreign", "身份不符"), ("duplicate", "同年度有冲突"), ("unusable", "不可用记录")])
def test_prerequisite_summary_full_listing_not_capped_answer_years(backend, kind, expected):
    first = document()
    second = document("2025-2026", raw="CS 5000")
    first = first.model_copy(update={"course_id": "c1", "course_code": "CS 5001", "course_name": "Synthetic 1"})
    second = second.model_copy(update={"course_id": "c1", "course_code": "CS 5001", "course_name": "Synthetic 1"})
    data = None
    if kind == "unavailable":
        data = {"schema_available": False}
    elif kind == "bad":
        data = {"documents": ["bad"]}
    elif kind not in {"none"}:
        if kind == "same":
            second = second.model_copy(update={"requisites": first.requisites})
        docs = [first] if kind in {"one", "unusable"} else [first, second]
        if kind == "foreign":
            docs = [document()]
        if kind == "duplicate":
            docs = [first, first]
        data = bundle(*docs, unusable_records=1 if kind == "unusable" else 0)
    backend.courses["c1"]["course_requisites"] = data
    app = comparison(["c1"])
    assert expected in text(app)
    assert "在详情里看完整规则" in text(app)
    assert not app.selectbox or all("先修规则" not in e.label for e in app.selectbox)
    if kind in {"same", "different"}:
        assert "2026-2027" in text(app) and "2025-2026" in text(app)


def test_all_failed_columns_keep_remove_and_clear_actions(backend):
    backend.failed.update(["c1", "c2"])
    app = comparison(["c1", "c2"])
    assert len(app.error) == 2
    assert [b.key for b in app.button if str(b.key).startswith("compare-remove-")] == ["compare-remove-c1", "compare-remove-c2"]
    assert not any(str(b.key).startswith("compare-view-") for b in app.button)
    app.button(key="compare-clear").click()
    run(app)
    assert not app.error and app.session_state["compare_course_ids"] == []


def test_read_budget_is_bounded_even_for_an_old_oversized_session(backend):
    app = comparison(["c1", "c2", "c3", "c4", "c5"])
    assert len(backend.reads) == 4
    assert not any(b.key == "compare-remove-c5" for b in app.button)
    assert "Synthetic 5" not in text(app)


def test_missing_evidence_does_not_claim_complete_data(backend):
    backend.courses["c1"].pop("answer_evidence")
    backend.courses["c2"]["answer_evidence"]["missing_fields"] = []
    app = comparison(["c1", "c2"])
    assert "缺失字段没有记录；不表示数据齐全" in text(app)
    assert "没有列出缺失项；不表示数据齐全" in text(app)
    assert "不表示不属于任何方案" in text(app)


def test_missing_catalog_capture_date_is_not_replaced_by_import_time(backend):
    backend.courses["c1"]["answer_evidence"]["catalog"] = {
        "course_code": "CS 5001", "course_name": "Synthetic 1", "description": None,
        "catalog_url": "https://catalog.northeastern.edu/course-descriptions/cs/", "snapshot_id": "catalog:" + "a" * 64,
        "imported_at": "2026-10-01T00:00:00Z"}
    app = comparison(["c1"])
    assert "目录抓取：没有记录" in text(app) and "目录存档没有描述记录" in text(app)
    assert "2026-10-01" not in text(app)


def test_older_fourth_edition_is_not_lost_or_replaced_by_chat_evidence(backend):
    docs = []
    for year in ["2023-2024", "2026-2027", "2024-2025", "2025-2026"]:
        doc = document(year, raw="CS 5000" if year == "2023-2024" else "CS 5010")
        docs.append(doc.model_copy(update={"course_id": "c1", "course_code": "CS 5001", "course_name": "Synthetic 1"}))
    backend.courses["c1"]["course_requisites"] = bundle(*docs)
    # An unrelated legacy chat summary is deliberately unusable: the full listing is authoritative here.
    backend.courses["c1"]["answer_evidence"]["requisites"] = {"storage": "schema_missing"}
    app = comparison(["c1"])
    years = next(e.value for e in app.text if e.value.startswith("已记录 Catalog 年份"))
    assert years.endswith("2026-2027、2025-2026、2024-2025、2023-2024")
    assert "条款不同" in text(app)


def test_unparsed_complete_clauses_differ_after_chat_cut(backend):
    from app.compare_view import requisite_summary

    docs = []
    for year, tail in [("2026-2027", "aaa"), ("2025-2026", "bbb")]:
        doc = document(year, raw="Permission " + "x" * 650 + tail)
        docs.append(doc.model_copy(update={"course_id": "c1", "course_code": "CS 5001", "course_name": "Synthetic 1"}))
    assert docs[0].requisites.prerequisite.status == "unparsed"
    backend.courses["c1"]["course_requisites"] = bundle(*docs)
    assert "条款不同" in "\n".join(requisite_summary(backend.courses["c1"]))


def test_corequisites_are_compared_independently_of_prerequisites(backend):
    from app.compare_view import requisite_summary
    from scrapers.course_requisites import parse_clause

    first, second = document(), document("2025-2026")
    second = second.model_copy(update={"requisites": second.requisites.model_copy(update={"corequisite": parse_clause("CS 5110")})})
    docs = [d.model_copy(update={"course_id": "c1", "course_code": "CS 5001", "course_name": "Synthetic 1"}) for d in [first, second]]
    course = {**backend.courses["c1"], "course_requisites": bundle(*docs)}
    assert "条款不同" in "\n".join(requisite_summary(course))


def test_actual_footer_is_present_not_just_its_css_class(backend):
    from app.ui_theme import footer_html

    app = comparison()
    assert footer_html() in [element.value for element in app.markdown]
