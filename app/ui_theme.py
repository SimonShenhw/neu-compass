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
"""


def inject_theme(st: object) -> None:
    """Inject the global stylesheet. Call once, right after set_page_config."""
    st.markdown(f"<style>{GLOBAL_CSS}</style>", unsafe_allow_html=True)


def hero_html(*, logged_in: bool = False, display_name: str = "") -> str:
    """Gradient hero banner — brand + tagline + status pills."""
    if logged_in and display_name:
        status_pill = f"👋 {html.escape(display_name)}"
    elif logged_in:
        status_pill = "👋 已登录"
    else:
        status_pill = "🔒 游客模式 · Guest"
    return (
        '<div class="nc-hero">'
        '<p class="nc-hero-title">🧭 NEU-Compass</p>'
        '<p class="nc-hero-sub">选课助手 · Course intelligence for NEU graduate students</p>'
        '<span class="nc-hero-pill">📚 6,469 courses indexed</span>'
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


__all__ = [
    "ALIPAY_BLUE",
    "GLOBAL_CSS",
    "course_header_html",
    "guest_banner_html",
    "hero_html",
    "inject_theme",
    "matched_via_badge",
    "topic_pills_html",
]
