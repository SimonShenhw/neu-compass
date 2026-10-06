"""Source/gap UI contracts without a browser or Streamlit server."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import re

import pytest

from app.answer_evidence_view import (
    FIELD_LABELS, SHORT_WARNING_LABELS, SOURCE_KIND_LABELS, WARNING_LABELS, _when, answer_markdown,
    evidence_summary, notice_line, render_answer_evidence, render_course_overview, render_field_evidence,
    render_streamed_answer, snapshot_digest, source_summary,
)
from app.streamlit_app import _format_evidence, _render_evidence_block
from db.catalog_source_repository import CatalogSourceRepository
from rag.answer_evidence import SOURCE_KIND_PREFIXES, course_answer_evidence, source_kind
from schemas.course import Course
from scrapers.neu_catalog import CatalogEntry

CATALOG = "https://catalog.northeastern.edu/course-descriptions/cs/"


class FakeSurface:
    def __init__(self):
        self.captions = []
        self.caption_help = []
        self.texts = []
        self.markdowns = []
        self.children = []
        self.expanders = []
        self.expander_surfaces = []
        self.session_state = {}

    def caption(self, value, **kwargs):
        self.captions.append(value)
        self.caption_help.append(kwargs.get("help"))

    def text(self, value):
        self.texts.append(value)

    def markdown(self, value, **kwargs):
        self.markdowns.append(value)

    def columns(self, sizes):
        pair = [FakeSurface() for _ in sizes]
        self.children.extend(pair)
        return pair

    def button(self, *args, **kwargs):
        return False

    def expander(self, label, **kwargs):
        # Its own surface, so a test can tell text inside the expander from text outside it.
        self.expanders.append(label)
        child = FakeSurface()
        self.expander_surfaces.append(child)
        return child

    def empty(self):
        child = FakeSurface()
        self.children.append(child)
        return child

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def evidence(*, catalog=False):
    record = Course(course_id="cs-5800", primary_code="CS 5800", primary_name="Algorithms")
    snapshot = CatalogSourceRepository.snapshot(CatalogEntry(
        course_code=record.primary_code, course_name=record.primary_name,
        description="Recorded description, not a live semester offering.",
        catalog_url="https://catalog.northeastern.edu/course-descriptions/cs/",
    )) if catalog else None
    return course_answer_evidence(record, snapshot).model_dump(mode="json")


def test_retrieval_notices_render_known_codes_only():
    """A known code becomes the fixed Chinese notice; unknown or hostile values
    (an older/compromised API) are dropped, never echoed as markdown."""
    from app.answer_evidence_view import RETRIEVAL_NOTICE_LABELS, render_retrieval_notices  # noqa: PLC0415

    surface = FakeSurface()
    render_retrieval_notices(surface, ["program_schedule_unverified", "[x](https://evil.example)", 3])
    assert surface.captions == ["ℹ️ " + RETRIEVAL_NOTICE_LABELS["program_schedule_unverified"]]
    for bad in (None, "program_schedule_unverified", {"a": 1}):
        quiet = FakeSurface()
        render_retrieval_notices(quiet, bad)
        assert quiet.captions == []


def test_absent_source_and_missing_fields_are_explicit():
    lines = evidence_summary(evidence())
    assert "未附可追溯" in lines[0]
    assert "每周工作量" in lines[1] and "难度" in lines[1]
    assert "缺失不等于零/简单/无要求" in lines[1]


def test_compact_cards_bound_the_gap_list_but_details_keep_every_field():
    data = evidence()
    compact, detail = FakeSurface(), FakeSurface()
    render_answer_evidence(compact, data)
    render_answer_evidence(detail, data, detailed=True)
    assert "详情查看全部" in compact.captions[1]
    assert FIELD_LABELS[data["missing_fields"][-1]] not in compact.captions[1]
    assert all(FIELD_LABELS[field] in detail.captions[1] for field in data["missing_fields"])


def test_compact_cards_do_not_hide_seed_conflict_or_synthetic_warnings():
    """Cards under an answer keep every important caveat, merged into ONE line (they used to add a
    caption per warning, several per course)."""
    data = evidence()
    data["warnings"] = ["program_seed_unverified", "catalog_metadata_conflict", "field_evidence_value_conflict",
                        "synthetic_record_not_real_course", "extracted_evidence_not_official_facts",
                        "catalog_retrieval_date_unknown"]
    st = FakeSurface()
    render_answer_evidence(st, data)
    notices = [line for line in st.captions if line.startswith("⚠️")]
    assert notices == ["⚠️ " + "；".join(SHORT_WARNING_LABELS[warning] for warning in data["warnings"][:5]) + "。"]
    assert SHORT_WARNING_LABELS["catalog_retrieval_date_unknown"] not in notices[0]  # Detail panel only.
    assert len(st.captions) == 3  # Source line, missing fields, one caveat line.


def test_notice_line_keeps_api_order_drops_repeats_and_unknown_codes():
    assert notice_line([]) is None and notice_line(["not_a_known_code"]) is None
    assert notice_line(["synthetic_record_not_real_course", "program_seed_unverified", "synthetic_record_not_real_course",
                        "not_a_known_code"]) == (
        "⚠️ " + SHORT_WARNING_LABELS["synthetic_record_not_real_course"] + "；"
        + SHORT_WARNING_LABELS["program_seed_unverified"] + "。")
    assert notice_line(["program_seed_unverified", "topics_source_unavailable"], only={"topics_source_unavailable"}) == (
        "⚠️ " + SHORT_WARNING_LABELS["topics_source_unavailable"] + "。")
    assert set(SHORT_WARNING_LABELS) == set(WARNING_LABELS)  # Every warning has both forms.


def test_course_overview_shows_the_description_its_source_and_one_caveat_line():
    data = evidence(catalog=True)
    data["warnings"].append("program_seed_unverified")
    st = FakeSurface()
    render_course_overview(st, data)
    assert st.texts == [data["catalog"]["description"]]
    assert st.captions[0] == f"课程描述来自 [NEU 官方课程目录]({data['catalog']['catalog_url']}) 的存档副本，不是实时核对。"
    assert st.captions[1] == notice_line(data["warnings"]) and len(st.captions) == 2
    missing = FakeSurface()
    render_course_overview(missing, evidence())  # No snapshot: say so once, not again in the caveat line.
    assert missing.texts == [] and missing.captions[0] == "没有官方目录描述的存档。"
    assert not any(SHORT_WARNING_LABELS["catalog_source_unavailable"] in line for line in missing.captions)
    corrupt = evidence(catalog=True)
    corrupt["catalog"]["catalog_url"] = "https://elsewhere.example/page"
    broken = FakeSurface()
    render_course_overview(broken, corrupt)
    assert broken.texts == [] and broken.captions[0].startswith("目录存档没有通过格式或来源校验")
    assert not any("elsewhere.example" in line for line in broken.captions + broken.markdowns)
    nothing = FakeSurface()
    render_course_overview(nothing, None)
    assert nothing.captions == nothing.texts == []


def test_snapshot_link_description_and_dates_have_separate_meaning():
    data = evidence(catalog=True)
    st = FakeSurface()
    render_answer_evidence(st, data, detailed=True)
    assert st.markdowns == [f"[官方目录来源]({data['catalog']['catalog_url']}) · 非实时核验"]
    assert st.texts == [data["catalog"]["description"]]
    digest = data["catalog"]["snapshot_id"].removeprefix("catalog:")
    line = next(line for line in st.captions if line.startswith("快照："))
    # The 64-hex digest is cut to its head; the whole ID is one hover away.
    assert line.startswith(f"快照：{digest[:12]}… · 导入：") and digest not in line
    assert re.fullmatch(r"快照：[0-9a-f]{12}… · 导入：\d{4}-\d\d-\d\d \d\d:\d\d UTC", line)
    assert st.caption_help[st.captions.index(line)] == f"完整快照 ID：{data['catalog']['snapshot_id']}"
    assert "抓取：未记录" in st.captions
    assert WARNING_LABELS["catalog_retrieval_date_unknown"] in st.captions


def test_times_show_to_the_minute_in_utc_and_a_naive_time_claims_no_zone():
    eastern = timezone(timedelta(hours=-4))
    assert _when(datetime(2026, 10, 1, 8, 34, 59, tzinfo=eastern)) == "2026-10-01 12:34 UTC"
    assert _when(datetime(2026, 10, 1, 8, 34, tzinfo=timezone.utc)) == "2026-10-01 08:34 UTC"
    assert _when(datetime(2026, 10, 1, 8, 34)) == "2026-10-01 08:34"
    data = evidence(catalog=True)
    data["catalog"]["retrieved_at"] = "2026-10-01T08:34:00-04:00"
    st = FakeSurface()
    render_answer_evidence(st, data, detailed=True)
    assert "抓取：2026-10-01 12:34 UTC" in st.captions


@pytest.mark.parametrize("snapshot_id", [
    "catalog:" + "0f" * 32 + " extra",  # A well-formed ID followed by more text.
    "x" + "catalog:" + "0f" * 32,  # Something in front of a well-formed ID.
])
def test_a_well_formed_digest_inside_a_longer_id_is_still_malformed(snapshot_id):
    """The whole ID must match: a prefix or substring match would put the full string into the
    tooltip, which renders Markdown."""
    assert snapshot_digest(snapshot_id) is None
    data = evidence(catalog=True)
    data["catalog"]["snapshot_id"] = snapshot_id
    st = FakeSurface()
    render_answer_evidence(st, data, detailed=True)
    line = next(line for line in st.captions if line.startswith("快照："))
    assert line.startswith("快照：格式异常 · 导入：")
    assert st.caption_help[st.captions.index(line)] is None


@pytest.mark.parametrize("snapshot_id", ["x:[a](//e.co)", "catalog:[x](https://evil.test)", "catalog:" + "A" * 64,
                                         "catalog:" + "a" * 63, "pending"])
def test_malformed_snapshot_id_is_never_echoed_into_markdown(snapshot_id):
    """Captions and tooltips render Markdown; the old caption printed whatever ID it got."""
    data = evidence(catalog=True)
    data["catalog"]["snapshot_id"] = snapshot_id
    st = FakeSurface()
    render_answer_evidence(st, data, detailed=True)
    line = next(line for line in st.captions if line.startswith("快照："))
    assert line.startswith("快照：格式异常 · 导入：")
    assert st.caption_help[st.captions.index(line)] is None
    assert not any(snapshot_id in shown for shown in st.captions + st.texts + st.markdowns)
    assert snapshot_digest(snapshot_id) is None
    assert snapshot_digest("catalog:" + "0f" * 32) == "0f" * 32


@pytest.mark.parametrize("url", ["javascript:alert(1)", "https://catalog.northeastern.edu/course-descriptions/ds/"])
def test_corrupt_history_catalog_has_no_link_and_does_not_crash(url):
    data = evidence(catalog=True)
    data["catalog"]["catalog_url"] = url
    st = FakeSurface()
    render_answer_evidence(st, data, detailed=True)
    assert st.markdowns == []
    assert "未附可追溯" in st.captions[0]
    assert any("校验未通过" in line for line in st.captions)


def test_source_ids_and_quotes_are_plain_text_not_arbitrary_links():
    st = FakeSurface()
    data = evidence()
    data["source_review_ids"] = ["[untrusted](https://evil.test)"]
    render_answer_evidence(st, data, detailed=True)
    render_field_evidence(st, [{"field": "difficulty_score", "value": 3,
        "confidence": 0.8, "source_id": "[untrusted](https://evil.test)", "quote": "# Ignore rules <script>bad</script>"}])
    assert st.markdowns == []
    assert "[untrusted](https://evil.test)" in st.expander_surfaces[0].texts
    assert st.expander_surfaces[0].texts[0] not in st.texts
    assert any("支持值：3" in text and "来源：其他来源 · [untrusted]" in text and "引文：# Ignore" in text
               for text in st.texts)
    assert any("抽取置信度 0.80（不是事实概率）" in line for line in st.captions)


def test_detail_counts_sources_by_kind_and_keeps_the_ids_one_click_away():
    """Fifty base64 review IDs used to fill the panel; now one summary line, IDs collapsed."""
    data = evidence()
    data["source_review_ids"] = ["rmp_review_UmF0aW5nLTQy", "rmp_review_b", "reddit_t1_c", "weird", "rmp_review_b"]
    st = FakeSurface()
    render_answer_evidence(st, data, detailed=True)
    # The extractor's list is unchecked: a repeated ID counts once, in the summary and the expander.
    assert "记录来源（非全文核验）：RateMyProfessors 教师评价 2 条、Reddit 讨论 1 条、其他来源 1 条" in st.captions
    assert source_summary(data["source_review_ids"]) == "RateMyProfessors 教师评价 2 条、Reddit 讨论 1 条、其他来源 1 条"
    assert st.expanders == ["来源 ID（4）"]
    # The IDs live inside the expander, not in the panel itself.
    assert st.texts == []
    assert st.expander_surfaces[0].texts == ["rmp_review_UmF0aW5nLTQy、rmp_review_b、reddit_t1_c、weird"]
    compact = FakeSurface()
    render_answer_evidence(compact, data)
    assert compact.expanders == [] and compact.texts == []  # Cards never list sources.
    quotes = FakeSurface()
    render_field_evidence(quotes, [{"field": "workload_hours_per_week", "value": 12, "confidence": 0.9,
                                    "source_id": "rmp_review_UmF0aW5nLTQy", "quote": "About 12 hours"}])
    assert quotes.texts == ["支持值：12\n来源：RateMyProfessors 教师评价 · rmp_review_UmF0aW5nLTQy\n引文：About 12 hours"]


@pytest.mark.parametrize("source_id, kind", [
    ("rmp_review_UmF0aW5nLTQy", "rmp_review"), ("reddit_t1_abc", "reddit"), ("syllabus_parsed", "syllabus"),
    ("synthetic_seed_2026_04_30", "synthetic"), ("catalog_neu-cs-5200", "catalog_derived"),
    ("rmp_reviewX", "other"), ("legacy_rmp_review_1", "other"), ("", "other"),
    ("catalog:" + "0f" * 32, "other"),  # A snapshot-style ID is not catalog-derived text.
])
def test_source_kinds_come_from_known_prefixes_only(source_id, kind):
    assert source_kind(source_id) == kind
    assert source_summary([source_id]) == f"{SOURCE_KIND_LABELS[kind]} 1 条"


def test_every_source_kind_has_a_ui_label():
    """A kind without a label would crash the detail panel (KeyError)."""
    assert set(SOURCE_KIND_LABELS) == {kind for _, kind in SOURCE_KIND_PREFIXES} | {"other"}
    assert SOURCE_KIND_LABELS == {
        "rmp_review": "RateMyProfessors 教师评价", "reddit": "Reddit 讨论", "syllabus": "课程大纲",
        "synthetic": "合成测试数据", "catalog_derived": "抽取时用的课程文本", "other": "其他来源",
    }


@pytest.mark.parametrize("raw, shown", [
    # Official catalog department pages stay clickable, as an inline link or a bare URL.
    (f"见 [NEU 官方课程目录]({CATALOG})。", f"见 [NEU 官方课程目录](<{CATALOG}>)。"),
    (f"[目录]({CATALOG} \"CS\")", f"[目录](<{CATALOG}> \"CS\")"),
    (f"来源：{CATALOG}。", f"来源：<{CATALOG}>。"),
    (f"（{CATALOG}）", f"（<{CATALOG}>）"),
    (f"<{CATALOG}>", f"<{CATALOG}>"),
    # Anything else keeps its words and loses its target.
    ("看[这里](https://evil.example/login)", "看[这里]"),
    (f"[x]({CATALOG}extra)", "[x]"),
    ("[x](http://catalog.northeastern.edu/course-descriptions/cs/)", "[x]"),
    ("[x](https://catalog.northeastern.edu.evil.example/course-descriptions/cs/)", "[x]"),
    ("[a [b] c](//evil.example)", "[a [b] c]"),
    ("[x]( <https://evil.example/a b> 't' )", "[x]"),
    ("[x](javascript:alert(1))", "[x])"),
    ("[x](relative/path)", "[x]"),
    ("[a](x)(//evil.example)", "[a]"),
    ("![x](https://evil.example/p.png)", "[x]"),
    (f"![x]({CATALOG})", f"[x](<{CATALOG}>)"),
    ("[x][r]\n[r]: //evil.example", "[x][r]\n[r]\\: //evil.example"),
    ("<https://[r]://evil.example>\n[x][r]", "[r]\\://evil.example\n[x][r]"),
    ("[label<https://x](//evil.example)>", "[labelx]"),
    ("<https://evil.example>", "evil.example"),
    (f"<{CATALOG}x>", "catalog.northeastern.edu/course-descriptions/cs/x"),
    ("visit https://evil.example/x, then", "visit evil.example/x, then"),
    ("HTTPS://EVIL.EXAMPLE and www.evil.example", "EVIL.EXAMPLE and evil.example"),
    ("https://https://evil.example www.https://evil.example", "evil.example evil.example"),
    ("https://a.example/https://evil.example", "a.example/evil.example"),
    ("`https://evil.example` it`s https://evil.example`", "`evil.example` it`s evil.example`"),
    ("plain text, 中文、no links", "plain text, 中文、no links"),
    ("a\x00b", "ab"),
])
def test_answer_markdown_keeps_only_official_catalog_links(raw, shown):
    assert answer_markdown(raw) == shown
    assert answer_markdown(shown) == shown  # Stable: rendering history twice changes nothing.


def test_live_and_history_answers_render_filtered_while_history_keeps_the_raw_text(monkeypatch):
    """Drives the real render() (the old check only searched its source text). The live answer goes
    through render_streamed_answer, history stores the raw text, and the student's own message
    renders as typed. AppTest merges the live pass and the immediate rerun into one element tree,
    so the first round of checks covers both passes together (the raw text appears in neither);
    the second round is a fresh run that renders from history alone."""
    import httpx  # noqa: PLC0415
    from streamlit.testing.v1 import AppTest  # noqa: PLC0415

    import app.answer_evidence_view as view  # noqa: PLC0415
    import app.api_client as api_module  # noqa: PLC0415
    import app.cookie_session as cookies  # noqa: PLC0415
    import app.discover_view as discover  # noqa: PLC0415
    import app.program_view as programs  # noqa: PLC0415
    import app.streamlit_app as main  # noqa: PLC0415
    import app.streamlit_auth_ui as auth  # noqa: PLC0415
    from config import settings  # noqa: PLC0415

    raw = f"Details: [the page](https://elsewhere.example/page) and the [NEU course catalog]({CATALOG})."
    question = "my own [note](https://elsewhere.example/mine)"
    assert answer_markdown(raw) != raw  # The filter has something to change here.
    tokens = [raw[:20], raw[20:45], raw[45:]]  # Split inside the first link.
    events = [{"type": "meta", "results": []}, *({"type": "token", "text": t} for t in tokens), {"type": "done"}]
    body = "".join(json.dumps(event) + "\n" for event in events).encode()

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"status": "ready", "courses_indexed": 3, "bm25_corpus": 3})
        assert request.url.path == "/chat"
        return httpx.Response(200, content=body)

    returned = []
    real = view.render_streamed_answer

    def spy(st, chunks):
        returned.append(real(st, chunks))
        return returned[-1]

    monkeypatch.setattr(view, "render_streamed_answer", spy)
    monkeypatch.setattr(settings, "answer_feedback_enabled", False)
    original = api_module.ApiClient
    monkeypatch.setattr(api_module, "ApiClient", lambda **kwargs: original(
        base_url="http://synthetic-widget", transport=httpx.MockTransport(handler), **kwargs))
    monkeypatch.setattr(auth, "handle_oauth_callback", lambda: None)
    monkeypatch.setattr(auth, "render_auth_sidebar", lambda: None)
    monkeypatch.setattr(cookies, "restore_login_from_cookie", lambda: False)
    monkeypatch.setattr(cookies, "flush_pending_cookie", lambda: None)
    monkeypatch.setattr(discover, "render_discover", lambda st: None)
    monkeypatch.setattr(programs, "get_programs_cached", lambda st: [])
    monkeypatch.setattr(main, "_render_filters_sidebar", lambda st, state: {})
    app = AppTest.from_string("from app.streamlit_app import render\nrender()").run(timeout=45)
    assert not app.exception
    app.chat_input[0].set_value(question).run(timeout=45)
    assert not app.exception
    assert returned == [raw]  # The live answer went through render_streamed_answer ...
    assert [msg["content"] for msg in app.session_state["messages"]] == [question, raw]  # ... history is raw.
    for _ in range(2):
        shown = [element.value for element in app.markdown]
        assert answer_markdown(raw) in shown and raw not in shown
        assert question in shown  # The student's own text is not rewritten.
        app.run(timeout=45)
        assert not app.exception
    assert returned == [raw]  # Reruns render from history; nothing is streamed again.


def test_history_filters_assistant_text_but_not_the_students_own():
    from app.streamlit_app import _render_message_text  # noqa: PLC0415

    st = FakeSurface()
    hostile = "see [login](https://evil.example) or https://evil.example"
    _render_message_text(st, {"role": "assistant", "content": hostile})
    _render_message_text(st, {"role": "user", "content": hostile})
    assert st.markdowns == ["see [login] or evil.example", hostile]


def test_every_partial_render_of_a_streamed_answer_is_filtered():
    st = FakeSurface()
    chunks = ["课程描述见 [NEU 目", "录](https://evil.exa", "mple/x)，另见 ", CATALOG[:20], CATALOG[20:], " 。"]
    raw = render_streamed_answer(st, iter(chunks))
    assert raw == "".join(chunks)  # History keeps the model's raw text.
    (placeholder,) = st.children
    assert len(placeholder.markdowns) == len(chunks)
    assert not any("https://evil" in shown for shown in placeholder.markdowns)
    assert placeholder.markdowns[-1] == f"课程描述见 [NEU 目录]，另见 <{CATALOG}> 。"
    assert render_streamed_answer(FakeSurface(), iter([])) == ""


def test_old_history_without_source_contract_remains_renderable():
    st = FakeSurface()
    render_answer_evidence(st, None)
    assert st.captions == st.texts == st.markdowns == []


def test_history_keeps_the_same_source_gap_contract():
    data = evidence(catalog=True)
    result = {"course_id": "cs-5800", "primary_code": "CS 5800", "primary_name": "Algorithms",
              "score": 0.4, "matched_via": "alias", "answer_evidence": data}
    formatted = _format_evidence([result])[0]
    assert formatted["answer_evidence"] == data
    assert "matched_via" not in formatted


def test_live_and_history_result_cards_use_shared_provenance_renderer():
    data = evidence()
    data["warnings"].append("program_seed_unverified")
    result = {"course_id": "cs-5800", "primary_code": "CS 5800", "primary_name": "Algorithms",
              "score": 0.4, "answer_evidence": data}
    for prefix in ["open-live", "history-0"]:
        st = FakeSurface()
        _render_evidence_block(st, [result], key_prefix=prefix)
        assert "未附可追溯" in st.children[0].captions[0]
        assert notice_line(["program_seed_unverified"]) in st.children[0].captions
