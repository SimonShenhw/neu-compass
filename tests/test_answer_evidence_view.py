"""Source/gap UI contracts without a browser or Streamlit server."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import random
import re
import time

import pytest

from app.answer_evidence_view import (
    FIELD_LABELS, SHORT_WARNING_LABELS, SOURCE_KIND_LABELS, WARNING_LABELS, _when, answer_markdown,
    evidence_summary, notice_line, render_answer_evidence, render_course_overview, render_field_evidence,
    render_streamed_answer, snapshot_digest, source_summary,
)
from app.streamlit_app import _format_evidence, _render_evidence_block
from db.catalog_source_repository import CatalogSourceRepository
from rag.answer_evidence import SOURCE_KIND_PREFIXES, course_answer_evidence, source_kind
from schemas.answer_evidence import OFFICIAL_CATALOG_URL
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


WJ = "\u2060"  # Word joiner: invisible, keeps the renderer from seeing a URL start.
OTHER = "https://elsewhere.example/notes"
OTHER_SHOWN = f"h{WJ}ttps://elsewhere.example/notes"
CATALOG_HREF = re.compile(OFFICIAL_CATALOG_URL.pattern + r"(?:#[A-Za-z0-9_-]+)?")
URL_START = re.compile(r"(?i)https?://|www\.")


CODE_TOKENS = {"code_inline", "code_block", "fence"}
# Streamlit-only syntax markdown-it does not model, judged on the text or the source instead:
# shortcodes (emoji, its logo image, material icons) are swapped in the decoded text; a directive
# can start at a ":" before anything but ASCII whitespace or punctuation; remark-math reads "$".
# 中文：markdown-it 不认识的 Streamlit 语法，改为检查解码后的文字或源文本：短代码（emoji、logo 图片、
# material 图标）在解码后的文字里替换；":" 后面只要不是 ASCII 空白或标点就可能开始一个指令；remark-math 读 "$"。
SHORTCODE = re.compile(r":(?:streamlit|material/[\w-]+|[A-Za-z0-9_][\w-]*):")
NAMED_COLON = re.compile(r"(\\*):(?=[^ \t\r\n!-/:-@\[-`{-~])")
DOLLAR = re.compile(r"(\\*)\$")


def rendered(markdown: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """CommonMark plus GFM tables and strikethrough as an independent judge: the (target, text) of
    every link, and the decoded visible text outside links as (token type, text), one piece per
    text node (a URL can only be recognised inside one). Raises on any image, raw HTML, reference
    definition (markdown-it keeps those out of the token stream, so they are read from env) or
    fenced block whose info string is math (Streamlit renders that as KaTeX). markdown-it accepts
    every link target here, so it never hides one the filter let through.
    中文：用 CommonMark（加 GFM 表格和删除线）独立判定：每个链接的（目标，文字），以及链接以外解码后的
    可见文字（token 类型，文字），每个文本节点一段（网址只能在单个节点里被识别）。出现图片、原始 HTML、
    引用式定义（markdown-it 不把它放进 token，从 env 里读）或信息串为 math 的代码块（Streamlit 会渲染成
    KaTeX）就报错。这里让 markdown-it 接受任何链接目标，免得它替过滤器挡掉。"""
    from markdown_it import MarkdownIt  # noqa: PLC0415  (locked, via rich)

    md = MarkdownIt("commonmark").enable(["table", "strikethrough"])
    md.validateLink = lambda url: True
    env: dict = {}
    links: list[tuple[str, str]] = []
    outside: list[tuple[str, str]] = []
    inside: list[str] | None = None
    href = ""

    def walk(tokens) -> None:
        nonlocal inside, href
        for token in tokens:
            assert token.type not in {"image", "html_inline", "html_block"}, token.type
            if token.type == "fence":
                assert (token.info.split() or [""])[0].lower() != "math", token.info
            if token.type == "link_open":
                href, inside = str(token.attrGet("href")), []
            elif token.type == "link_close":
                links.append((href, "".join(inside or [])))
                inside = None
            elif token.children:
                walk(token.children)
            elif token.type in {"text", "softbreak", "hardbreak"} | CODE_TOKENS:
                piece = "\n" if token.type.endswith("break") else token.content
                if inside is None:
                    outside.append((token.type, piece))
                else:
                    inside.append(piece)

    walk(md.parse(markdown, env))
    assert not env.get("references"), env.get("references")  # A definition turns "[x]" into a link.
    return links, outside


def assert_inert(markdown: str) -> str:
    """Only catalog links (or a mail link, the accepted cost). Visible text has no URL start,
    except a catalog autolink's own text and a kept catalog URL inside code (code is never
    linked; it shows there in angle brackets), and no Streamlit shortcode; in the source, every
    "$" and every ":" a directive name could follow is escaped. Returns the visible text outside
    links. 中文：只有目录链接（或邮件链接，已接受的代价）。可见文字里没有网址开头（例外只有目录自动
    链接自己的文字，以及代码里保留的目录网址：代码不会变成链接，那里会带尖括号显示），也没有 Streamlit
    短代码；源文本里每个 "$"、每个后面可能跟指令名的 ":" 都已转义。返回链接以外的可见文字。"""
    links, outside = rendered(markdown)
    for href, text in links:
        assert CATALOG_HREF.fullmatch(href) or href.startswith("mailto:"), href
        assert not URL_START.search(text) or text == href, text
    for kind, piece in outside:
        for match in URL_START.finditer(piece):
            assert kind in CODE_TOKENS and CATALOG_HREF.match(piece, match.start()), (kind, piece)
        assert not SHORTCODE.search(piece), piece
    for pattern in (NAMED_COLON, DOLLAR):  # An odd run of backslashes escapes the character.
        assert all(len(match.group(1)) % 2 for match in pattern.finditer(markdown)), markdown
    return "".join(piece for _, piece in outside)


EXPECTED = [
    # Ordinary formatting is untouched.
    ("**CS 5800** is *hard*; see `code`.\n\n- one\n- two", None),
    ("## 标题\n\n> 引用\n\n| a | b |\n|---|---|\n| 1 | 2 |", None),
    ("a < b, a & b, Note: 3 hours. 中文：冒号", None),
    ("name@elsewhere.example", None),  # A mail link may remain (the accepted cost).
    # Official catalog links stay clickable; their labels are escaped like everything else.
    (f"[CS 目录]({CATALOG})", None),
    (f"[CS 5800]({CATALOG}#cs5800)", None),
    (f'[CS](<{CATALOG}> "Catalog")', f"[CS]({CATALOG})"),
    (f"See {CATALOG}.", f"See <{CATALOG}>."),
    (f"<{CATALOG}>", None),
    (f"[CS $1 &amp; <b>]({CATALOG})", f"[CS \\$1 \\&amp; \\<b>]({CATALOG})"),
    (f"[{OTHER}]({CATALOG})", f"[{OTHER_SHOWN}]({CATALOG})"),
    (f"![CS]({CATALOG})", f"\\![CS]({CATALOG})"),
    # A label never spans brackets, so the text before a catalog link cannot swallow it.
    (f"[x]({OTHER})]({CATALOG})", f"[x]\\({OTHER_SHOWN})]\\(<{CATALOG}>)"),
    # Anything else shows as written.
    (f"[notes]({OTHER})", f"[notes]\\({OTHER_SHOWN})"),
    (f"![chart]({OTHER})", f"\\![chart]\\({OTHER_SHOWN})"),
    (f"<{OTHER}>", f"\\<{OTHER_SHOWN}>"),
    (f"{OTHER} and www.elsewhere.example", f"{OTHER_SHOWN} and w{WJ}ww.elsewhere.example"),
    ("HTTP://ELSEWHERE.EXAMPLE WWW.ELSEWHERE.EXAMPLE", f"H{WJ}TTP://ELSEWHERE.EXAMPLE W{WJ}WW.ELSEWHERE.EXAMPLE"),
    (f"[notes]: {OTHER}", f"[notes]\\: {OTHER_SHOWN}"),
    ("[^1]: a note", "[^1]\\: a note"),
    ("&#104; &amp; AT&T", "\\&#104; \\&amp; AT\\&T"),
    ("<b>bold</b> <!-- c --> <?x?>", "\\<b>bold\\</b> \\<!-- c --> \\<?x?>"),
    ("$x$ and $1,200", "\\$x\\$ and \\$1,200"),
    (":red[note] :smile: ::note 3:1", f"\\:{WJ}red[note] \\:{WJ}smile: :\\:{WJ}note 3\\:{WJ}1"),
    # Streamlit swaps shortcodes in the decoded text, so the name must not touch the colon.
    ("a :streamlit: [x]:material/home: a", f"a \\:{WJ}streamlit: [x]\\:{WJ}material/home: a"),
    ("a\\b \\*x\\* \\<b>", "a\\\\b \\\\*x\\\\* \\\\\\<b>"),
    ("`a<b`", "`a\\<b`"),  # Inserted escapes are visible inside code (a cost),
    (f"`{CATALOG}`", f"`<{CATALOG}>`"),  # and so are a kept catalog URL's angle brackets.
    # Streamlit renders a ```math block as KaTeX when the answer has a "$...$" pair anywhere.
    ("$x$\n\n```math\ny\n```", f"\\$x\\$\n\n```m{WJ}ath\ny\n```"),
    ("> ~~~ Math\n> y\n> ~~~", f"> ~~~ M{WJ}ath\n> y\n> ~~~"),
    # A directive name may be any non-ASCII character, and the renderer's whitespace is narrower
    # than Python's \s (which includes U+001C).
    ("a :中文[x] a", f"a \\:{WJ}中文[x] a"),
    (":" + chr(0x1C) + "x[y]", f"\\:{WJ}" + chr(0x1C) + "x[y]"),
    ("\ue0000\ue001", "\ufffd0\ufffd"),  # The model cannot forge a placeholder.
]


@pytest.mark.parametrize("raw, shown", EXPECTED)
def test_answer_markdown_exact_output(raw, shown):
    assert answer_markdown(raw) == (raw if shown is None else shown)


@pytest.mark.parametrize("raw", [raw for raw, _ in EXPECTED])
def test_a_markdown_parser_finds_only_catalog_links_and_no_image_or_html(raw):
    assert_inert(answer_markdown(raw))


def test_catalog_links_survive_and_point_where_they_said():
    links, outside = rendered(answer_markdown(f"[CS 目录]({CATALOG}#cs5800) or {CATALOG}."))
    assert links == [(CATALOG + "#cs5800", "CS 目录"), (CATALOG, CATALOG)]
    assert "".join(piece for _, piece in outside) == " or ."


# Markdown-significant fragments, combined at random with a fixed seed: an independent search for
# any input that renders as something other than catalog links and text.
# 中文：把 Markdown 里有意义的片段按固定种子随机拼接，独立地找有没有哪个输入会渲染出目录链接和文字以外的东西。
FRAGMENTS = [
    "[", "]", "(", ")", "<", ">", "!", "&", "#", ";", "\\", ":", "$", "`", "*", "_", "~", "|", "^", '"',
    "'", "=", "-", " ", "  ", "\n", "\n\n", "a", "x", "1", "104", "x68", "amp", "h", "ttp", "s", "://",
    "```", "~~~", "math", "streamlit", "smile", "material/home", "help", "中文",
    "w", "ww", ".", "/", "@", "elsewhere.example", CATALOG, CATALOG[:-1], "#cs5800", "red", "\ue000",
    "\ue001", "0",
]
# Without formatting characters, newlines or "@", what the parser shows is exactly the input.
PLAIN_FRAGMENTS = [
    "[", "]", "(", ")", "<", ">", "!", "&", "#", ";", "\\", ":", "$", '"', "'", "=", " ", "a", "x", "1",
    "104", "x68", "amp", "h", "ttp", "s", "://", "w", "ww", ".", "/", "elsewhere.example", "red",
    "streamlit", "smile", "material/home", "help", "中文",
]


def samples(fragments: list[str], seed: int, count: int = 1500, longest: int = 24) -> list[str]:
    rng = random.Random(seed)
    return ["".join(rng.choice(fragments) for _ in range(rng.randint(1, longest))) for _ in range(count)]


@pytest.mark.parametrize("seed", range(4))
def test_no_combination_of_markdown_fragments_renders_anything_but_catalog_links(seed):
    for raw in samples(FRAGMENTS, seed):
        assert_inert(answer_markdown(raw))


@pytest.mark.parametrize("seed", range(4))
def test_plain_text_renders_exactly_as_written(seed):
    for sample in samples(PLAIN_FRAGMENTS, 100 + seed):
        raw = f"a {sample} a"  # Nothing at the start or end of a line to strip or interpret.
        assert assert_inert(answer_markdown(raw)).replace(WJ, "") == raw


@pytest.mark.parametrize("unit", [
    "[a](b", "](", "]:", "![", "<a", "&#", "&a", "\\", "$", ":a", "h", "https://", "www.", "[",
    "[" + "a" * 199, f"[a]({CATALOG}", f"<{CATALOG}", CATALOG, "```" + " " * 97, "``` m", "\ue000",
])
def test_filtering_takes_linear_time(unit):
    text = (unit * (200_000 // len(unit) + 1))[:200_000]  # About three times the longest answer.
    started = time.perf_counter()
    answer_markdown(text)
    assert time.perf_counter() - started < 2.0


def test_history_filters_assistant_text_but_not_the_students_own():
    from app.streamlit_app import _render_message_text

    st = FakeSurface()
    content = f"[notes]({OTHER}) costs $5"
    _render_message_text(st, {"role": "assistant", "content": content})
    _render_message_text(st, {"role": "user", "content": content})
    assert st.markdowns == [f"[notes]\\({OTHER_SHOWN}) costs \\$5", content]


def test_streaming_renders_at_most_once_per_interval_and_always_the_final_text():
    st = FakeSurface()
    chunks = ["See ", "[notes](ht", "tps://elsewhere.example/notes)", " and ", f"[CS]({CATALOG[:20]}",
              f"{CATALOG[20:]})."]
    times = iter([0.0, 0.05, 0.10, 0.19, 0.30, 0.31])
    raw = render_streamed_answer(st, iter(chunks), min_interval=0.1, clock=lambda: next(times))
    assert raw == "".join(chunks)
    placeholder, = st.children
    assert placeholder.markdowns == [answer_markdown("".join(chunks[:n])) for n in (1, 3, 5, 6)]
    for shown in placeholder.markdowns:
        assert_inert(shown)


def test_a_link_split_across_tokens_is_never_rendered_raw():
    st = FakeSurface()
    raw = f"See [notes]({OTHER}) and [CS]({CATALOG})."
    chunks = [raw[i:i + 3] for i in range(0, len(raw), 3)]
    ticks = iter(range(len(chunks)))
    assert render_streamed_answer(st, iter(chunks), clock=lambda: float(next(ticks))) == raw
    placeholder, = st.children
    assert len(placeholder.markdowns) == len(chunks)  # A slow stream renders every token.
    for n, shown in enumerate(placeholder.markdowns, start=1):
        assert shown == answer_markdown("".join(chunks[:n]))
        assert_inert(shown)


def test_the_default_interval_is_a_tenth_of_a_second():
    st = FakeSurface()
    times = iter([0.0, 0.05, 0.1, 0.15])
    render_streamed_answer(st, iter(["a", "b", "c", "d"]), clock=lambda: next(times))
    placeholder, = st.children
    assert placeholder.markdowns == ["a", "abc", "abcd"]


def test_a_fast_stream_renders_twice_and_an_empty_one_not_at_all():
    st = FakeSurface()
    assert render_streamed_answer(st, iter(["a"] * 10_000), clock=lambda: 5.0) == "a" * 10_000
    placeholder, = st.children
    assert placeholder.markdowns == ["a", "a" * 10_000]
    empty = FakeSurface()
    assert render_streamed_answer(empty, iter([])) == ""
    assert empty.children[0].markdowns == []


def test_a_stream_that_fails_midway_still_shows_its_text_filtered():
    def chunks():
        yield "[notes]("
        yield f"{OTHER}) so far"
        raise RuntimeError("stream ended")

    st = FakeSurface()
    times = iter([0.0, 0.01])
    with pytest.raises(RuntimeError, match="stream ended"):
        render_streamed_answer(st, chunks(), clock=lambda: next(times))
    placeholder, = st.children
    assert placeholder.markdowns == [answer_markdown("[notes]("), answer_markdown(f"[notes]({OTHER}) so far")]


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

    raw = f"Notes: see [the notes](https://elsewhere.example/notes) and the [CS catalog]({CATALOG})."
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
