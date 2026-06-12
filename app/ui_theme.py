"""Alipay-inspired visual theme for the Streamlit UI (2026-06 frontend pass).

Design language (支付宝风):
  - Primary: Alipay blue #1677FF on a cool-gray canvas #F5F7FA
  - White cards with 14-18px radius and soft layered shadows
  - Pill-shaped chips / badges everywhere; gradient hero banner
  - Quiet borders (#EBEEF5) instead of hard dividers

All builders here are PURE string functions (no streamlit import at module
top) so tests can cover them without the Streamlit runtime — same pattern
as state_manager / streamlit_app helpers. `inject_theme(st)` is the single
side-effecting entry point; page modules call it right after
st.set_page_config.

Dynamic values are html-escaped in every builder — course names scraped
from the catalog can legally contain `&`, `<`, quotes.
"""

from __future__ import annotations

import html

ALIPAY_BLUE = "#1677FF"

# matched_via → (label, background, foreground). Mirrors the API's
# matched_via vocabulary (api/routes/search.py): alias / hybrid / program /
# rejected / empty.
_BADGE_STYLES: dict[str, tuple[str, str, str]] = {
    "alias": ("直达 · alias", "#E6F7EE", "#18A058"),
    "hybrid": ("检索 · hybrid", "#E8F1FF", ALIPAY_BLUE),
    "program": ("培养方案 · program", "#F0EBFF", "#7B61FF"),
    "rejected": ("无匹配 · rejected", "#FFF1E6", "#E8731A"),
    "empty": ("空结果 · empty", "#F2F3F5", "#646A73"),
}

GLOBAL_CSS = """
/* ===== Canvas ===== */
.stApp {
  background: linear-gradient(180deg, #EAF1FB 0%, #F5F7FA 260px, #F5F7FA 100%);
}
.block-container { padding-top: 1.1rem; max-width: 1180px; }
header[data-testid="stHeader"] { background: transparent; }
#MainMenu, footer { visibility: hidden; }

/* ===== Typography ===== */
h3 { font-weight: 600; color: #26303E; letter-spacing: 0.2px; }

/* ===== Sidebar ===== */
[data-testid="stSidebar"] {
  background: #FFFFFF;
  border-right: 1px solid #E8ECF3;
}

/* ===== Buttons → Alipay pills ===== */
.stButton > button {
  border-radius: 12px;
  border: 1px solid #E5E9F2;
  background: #FFFFFF;
  color: #3D4757;
  font-weight: 500;
  box-shadow: 0 1px 2px rgba(31, 56, 88, 0.04);
  transition: all 0.15s ease;
}
.stButton > button:hover {
  border-color: #1677FF;
  color: #1677FF;
  box-shadow: 0 4px 14px rgba(22, 119, 255, 0.18);
  transform: translateY(-1px);
}
.stButton > button:focus:not(:active) {
  border-color: #1677FF;
  color: #1677FF;
}

/* ===== Chat bubbles → white cards ===== */
[data-testid="stChatMessage"] {
  background: #FFFFFF;
  border: 1px solid #EBEEF5;
  border-radius: 16px;
  padding: 0.85rem 1.05rem;
  box-shadow: 0 2px 8px rgba(31, 56, 88, 0.05);
  margin-bottom: 0.35rem;
}

/* ===== Chat input → rounded search bar ===== */
[data-testid="stChatInput"] {
  border-radius: 14px;
  border: 1.5px solid #D9E2F1;
  background: #FFFFFF;
  box-shadow: 0 2px 10px rgba(31, 56, 88, 0.06);
}
[data-testid="stChatInput"]:focus-within {
  border-color: #1677FF;
  box-shadow: 0 2px 16px rgba(22, 119, 255, 0.22);
}

/* ===== Expanders → cards ===== */
[data-testid="stExpander"] {
  background: #FFFFFF;
  border: 1px solid #EBEEF5;
  border-radius: 12px;
  box-shadow: 0 1px 4px rgba(31, 56, 88, 0.04);
}

/* ===== Alerts soften ===== */
[data-testid="stAlert"] { border-radius: 12px; }

/* ===== Custom components (nc- prefix = neu-compass) ===== */
.nc-hero {
  background: linear-gradient(135deg, #1677FF 0%, #3D8BFF 55%, #66A6FF 100%);
  border-radius: 20px;
  padding: 26px 30px 22px;
  color: #FFFFFF;
  box-shadow: 0 10px 28px rgba(22, 119, 255, 0.28);
  margin-bottom: 1.1rem;
}
.nc-hero-title {
  font-size: 1.7rem;
  font-weight: 700;
  margin: 0;
  color: #FFFFFF;
  letter-spacing: 0.4px;
}
.nc-hero-sub {
  margin: 6px 0 14px;
  color: rgba(255, 255, 255, 0.88);
  font-size: 0.95rem;
}
.nc-hero-pill {
  display: inline-block;
  background: rgba(255, 255, 255, 0.18);
  border: 1px solid rgba(255, 255, 255, 0.28);
  color: #FFFFFF;
  padding: 3px 12px;
  border-radius: 999px;
  font-size: 0.78rem;
  margin-right: 8px;
  backdrop-filter: blur(4px);
}

.nc-banner {
  background: #FFFFFF;
  border: 1px solid #EBEEF5;
  border-left: 4px solid #1677FF;
  border-radius: 12px;
  padding: 12px 16px;
  color: #3D4757;
  font-size: 0.9rem;
  box-shadow: 0 1px 4px rgba(31, 56, 88, 0.04);
  margin-bottom: 0.9rem;
}

.nc-card {
  background: #FFFFFF;
  border: 1px solid #EBEEF5;
  border-radius: 16px;
  padding: 18px 20px;
  box-shadow: 0 2px 10px rgba(31, 56, 88, 0.06);
  margin-bottom: 0.9rem;
}
.nc-card-code {
  color: #1677FF;
  font-weight: 700;
  font-size: 1.15rem;
  letter-spacing: 0.3px;
}
.nc-card-name {
  color: #26303E;
  font-weight: 600;
  font-size: 1.05rem;
  margin: 2px 0 12px;
}

.nc-meta-row { display: flex; gap: 10px; flex-wrap: wrap; }
.nc-meta-chip {
  background: #F5F7FA;
  border: 1px solid #EBEEF5;
  border-radius: 10px;
  padding: 6px 14px;
  text-align: center;
  min-width: 86px;
}
.nc-meta-label {
  display: block;
  color: #8A94A6;
  font-size: 0.72rem;
  margin-bottom: 1px;
}
.nc-meta-value {
  display: block;
  color: #26303E;
  font-weight: 600;
  font-size: 0.95rem;
}

.nc-pill {
  display: inline-block;
  background: #E8F1FF;
  color: #1677FF;
  border-radius: 999px;
  padding: 3px 12px;
  font-size: 0.8rem;
  margin: 0 6px 6px 0;
}

.nc-badge {
  display: inline-block;
  border-radius: 999px;
  padding: 2px 10px;
  font-size: 0.75rem;
  font-weight: 600;
  vertical-align: middle;
}

/* ===== Result cards (chat evidence, UI round 2) ===== */
.nc-result-card {
  background: #FFFFFF;
  border: 1px solid #EBEEF5;
  border-radius: 12px;
  padding: 10px 14px;
  box-shadow: 0 1px 4px rgba(31, 56, 88, 0.04);
  margin-bottom: 2px;
}
.nc-result-rank {
  display: inline-block;
  min-width: 22px;
  text-align: center;
  background: #F0F5FF;
  color: #1677FF;
  border-radius: 8px;
  font-size: 0.75rem;
  font-weight: 700;
  padding: 1px 4px;
  margin-right: 8px;
}
.nc-result-code { color: #1677FF; font-weight: 700; }
.nc-result-name { color: #26303E; }
.nc-score-track {
  height: 5px;
  background: #F2F3F5;
  border-radius: 999px;
  margin-top: 7px;
  overflow: hidden;
}
.nc-score-fill {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #1677FF, #66A6FF);
}
.nc-score-num { color: #8A94A6; font-size: 0.72rem; float: right; }

/* ===== Program-context block (course detail) ===== */
.nc-prog-row {
  background: #FFFFFF;
  border: 1px solid #EBEEF5;
  border-left: 4px solid #1677FF;
  border-radius: 12px;
  padding: 10px 14px;
  margin-bottom: 8px;
}
.nc-prog-name { color: #26303E; font-weight: 600; font-size: 0.92rem; }
.nc-prog-meta { margin-top: 4px; }

/* ===== Empty state (detail column) ===== */
.nc-empty {
  background: #FFFFFF;
  border: 1px dashed #D9E2F1;
  border-radius: 16px;
  padding: 38px 24px;
  text-align: center;
  color: #8A94A6;
}
.nc-empty-icon { font-size: 2rem; margin-bottom: 8px; }

/* ===== Sidebar brand ===== */
.nc-side-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 2px 10px;
  border-bottom: 1px solid #F0F2F7;
  margin-bottom: 6px;
}
.nc-side-brand-logo {
  width: 36px; height: 36px;
  border-radius: 10px;
  background: linear-gradient(135deg, #1677FF, #66A6FF);
  color: #FFF;
  display: flex; align-items: center; justify-content: center;
  font-size: 1.1rem;
}
.nc-side-brand-name { color: #26303E; font-weight: 700; line-height: 1.15; }
.nc-side-brand-sub { color: #8A94A6; font-size: 0.72rem; }

/* ===== Footer ===== */
.nc-footer {
  text-align: center;
  color: #A6AEBC;
  font-size: 0.75rem;
  padding: 18px 0 6px;
}
"""


def inject_theme(st: object) -> None:
    """Inject the global stylesheet. Call once, right after set_page_config."""
    st.markdown(f"<style>{GLOBAL_CSS}</style>", unsafe_allow_html=True)


def hero_html(
    *,
    logged_in: bool = False,
    display_name: str = "",
    courses_indexed: int | None = None,
) -> str:
    """Gradient hero banner — brand + tagline + status pills.

    courses_indexed comes from /ready at render time; None (API not
    reachable yet) falls back to wording without a hardcoded number —
    the previous literal went stale every re-scrape."""
    if logged_in and display_name:
        status_pill = f"👋 {html.escape(display_name)}"
    elif logged_in:
        status_pill = "👋 已登录"
    else:
        status_pill = "🔒 游客模式 · Guest"
    if courses_indexed:
        corpus_pill = f"📚 {courses_indexed:,} courses indexed"
    else:
        corpus_pill = "📚 Full NEU graduate catalog"
    return (
        '<div class="nc-hero">'
        '<p class="nc-hero-title">🧭 NEU-Compass</p>'
        '<p class="nc-hero-sub">选课助手 · Course intelligence for NEU graduate students</p>'
        f'<span class="nc-hero-pill">{corpus_pill}</span>'
        '<span class="nc-hero-pill">⚡ alias → ontology → hybrid RAG</span>'
        f'<span class="nc-hero-pill">{status_pill}</span>'
        "</div>"
    )


def guest_banner_html() -> str:
    """Soft card replacing the default st.info guest notice."""
    return (
        '<div class="nc-banner">🔒 当前为游客浏览 — 仅可见 level-0 (preview) '
        "Co-op 数据。用 NEU 邮箱登录（左侧栏）解锁贡献分级内容。</div>"
    )


def matched_via_badge(matched_via: str) -> str:
    """Colored pill for the API's matched_via field. Unknown values fall
    back to the neutral 'empty' style so a new backend tier can't break
    the UI."""
    label, bg, fg = _BADGE_STYLES.get(matched_via, _BADGE_STYLES["empty"])
    return (
        f'<span class="nc-badge" style="background:{bg};color:{fg};">'
        f"{html.escape(label)}</span>"
    )


def course_header_html(
    *,
    code: str,
    name: str,
    term: str | None = None,
    credits: int | str | None = None,
    delivery_mode: str | None = None,
) -> str:
    """Course-detail header card: blue code + name + meta chips row.
    Replaces the old st.metric trio (whose look fought the card design)."""
    chips = ""
    for label, value in (
        ("Term", term),
        ("Credits", credits),
        ("Mode", str(delivery_mode).replace("_", " ") if delivery_mode else None),
    ):
        shown = html.escape(str(value)) if value not in (None, "") else "—"
        chips += (
            '<div class="nc-meta-chip">'
            f'<span class="nc-meta-label">{label}</span>'
            f'<span class="nc-meta-value">{shown}</span>'
            "</div>"
        )
    return (
        '<div class="nc-card">'
        f'<span class="nc-card-code">{html.escape(code)}</span>'
        f'<p class="nc-card-name">{html.escape(name)}</p>'
        f'<div class="nc-meta-row">{chips}</div>'
        "</div>"
    )


def topic_pills_html(topics: list[str]) -> str:
    """Topics as Alipay-style light-blue pills. Empty list → empty string."""
    if not topics:
        return ""
    pills = "".join(
        f'<span class="nc-pill">{html.escape(t)}</span>' for t in topics
    )
    return f"<div>{pills}</div>"


def result_card_html(
    *, rank: int, code: str, name: str, score: float, pct: int,
) -> str:
    """One search-result card: rank chip + code + name + score bar.

    pct (0-100) is the bar width — caller normalizes against the top hit
    in the SAME result list, so the bar reads as relative confidence
    within this answer, not a cross-query absolute."""
    pct = max(0, min(100, int(pct)))
    return (
        '<div class="nc-result-card">'
        f'<span class="nc-result-rank">{int(rank)}</span>'
        f'<span class="nc-result-code">{html.escape(code)}</span> '
        f'<span class="nc-result-name">{html.escape(name)}</span>'
        f'<span class="nc-score-num">{score:.3f}</span>'
        '<div class="nc-score-track">'
        f'<div class="nc-score-fill" style="width:{pct}%;"></div>'
        "</div></div>"
    )


# requirement_type → (中英 label, background, foreground). Mirrors the
# RequirementType literal in schemas/program.py.
_REQ_BADGE_STYLES: dict[str, tuple[str, str, str]] = {
    "core": ("核心 · core", "#FFF1E6", "#E8731A"),
    "foundation": ("基础 · foundation", "#E8F1FF", ALIPAY_BLUE),
    "elective_pool": ("选修池 · elective", "#E6F7EE", "#18A058"),
    "capstone": ("毕业项目 · capstone", "#F0EBFF", "#7B61FF"),
}

# prereq requirement → 中文 label. Mirrors PrereqRequirement.
_PREREQ_LABELS: dict[str, str] = {
    "required": "必须先修",
    "recommended": "建议先修",
    "concurrent": "可同修",
}


def requirement_badge(requirement_type: str) -> str:
    """Colored pill for a program-edge requirement_type. Unknown values
    fall back to the foundation style (neutral blue)."""
    label, bg, fg = _REQ_BADGE_STYLES.get(
        requirement_type, _REQ_BADGE_STYLES["foundation"],
    )
    return (
        f'<span class="nc-badge" style="background:{bg};color:{fg};">'
        f"{html.escape(label)}</span>"
    )


def program_context_html(edges: list[dict]) -> str:
    """培养方案 rows for the course-detail panel. Each edge dict carries
    program_name / requirement_type / semester_recommended (the
    /course/{id} program_context shape). Empty list → empty string."""
    if not edges:
        return ""
    rows = ""
    for e in edges:
        sem = e.get("semester_recommended")
        sem_chip = (
            f'<span class="nc-pill">第 {int(sem)} 学期推荐</span>' if sem else ""
        )
        rows += (
            '<div class="nc-prog-row">'
            f'<div class="nc-prog-name">🎓 {html.escape(str(e.get("program_name", "")))}</div>'
            f'<div class="nc-prog-meta">{requirement_badge(str(e.get("requirement_type", "")))} '
            f"{sem_chip}</div>"
            "</div>"
        )
    return rows


def prereq_label_md(
    *, code: str | None, name: str | None, course_id: str, requirement: str,
) -> str:
    """Markdown line for one prerequisite row (the Open button next to it
    is a Streamlit widget, so this stays markdown rather than HTML)."""
    shown = f"**{code}** — {name}" if code and name else f"`{course_id}`"
    req = _PREREQ_LABELS.get(requirement, requirement)
    return f"{shown}  \n*{req}*"


def empty_detail_html() -> str:
    """Friendly empty state for the detail column (replaces st.info)."""
    return (
        '<div class="nc-empty">'
        '<div class="nc-empty-icon">📘</div>'
        "点击左侧搜索结果中的课程<br>查看课程详情、培养方案定位与先修关系"
        "</div>"
    )


def sidebar_brand_html() -> str:
    """Compact brand block pinned at the top of the sidebar."""
    return (
        '<div class="nc-side-brand">'
        '<div class="nc-side-brand-logo">🧭</div>'
        '<div><div class="nc-side-brand-name">NEU-Compass</div>'
        '<div class="nc-side-brand-sub">选课助手 · for NEU students</div></div>'
        "</div>"
    )


def footer_html() -> str:
    """Page footer disclaimer."""
    return (
        '<div class="nc-footer">'
        "NEU-Compass 为非官方学生工具 · 课程数据可能滞后，选课请以官方目录为准 · "
        "非商业 / F1 合规"
        "</div>"
    )


__all__ = [
    "ALIPAY_BLUE",
    "GLOBAL_CSS",
    "course_header_html",
    "empty_detail_html",
    "footer_html",
    "guest_banner_html",
    "hero_html",
    "inject_theme",
    "matched_via_badge",
    "prereq_label_md",
    "program_context_html",
    "requirement_badge",
    "result_card_html",
    "sidebar_brand_html",
    "topic_pills_html",
]
