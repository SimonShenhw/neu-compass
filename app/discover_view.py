"""Landing-page discovery block — shown only while chat history is empty.

落地页发现区块 —— 仅在聊天历史为空时展示。

Cold-start users land on an empty chat column and don't know what the
product can do beyond the sample-query chips (Week 8 review finding). This
block turns the blank space into three teasers, each one click from real
content:

  🎓 按培养方案浏览 — program chips → the Programs page (curriculum view)
  🔥 入门推荐       — one semester-1 core/foundation course per featured
                      program → course detail on the search page
  💼 Co-op 风向     — two recent Co-op one-liners → the Co-op page

冷启动用户落地在一个空的聊天列，除了示例查询 chips 之外不知道产品还能
做什么（第 8 周评审发现的问题）。这个区块把空白空间变成三个"预告"，
每个都只需一次点击就能触达真实内容：

  🎓 按培养方案浏览 —— 培养方案 chips → Programs 页面（课程表视图）
  🔥 入门推荐       —— 每个精选培养方案各挑一门第一学期核心/基础课
                      → 搜索页的课程详情
  💼 Co-op 风向     —— 两条最近的 Co-op 一句话摘要 → Co-op 页面

The main app owns navigation; this module only sets flags + st.rerun():
  - pending_nav_to_programs (+ selected_program_id) — program chip click
  - pending_nav_to_coop — Co-op "去看看" click
  - selected_course_id — 入门推荐 查看 click (stays on the search page)

导航由主 app 掌管；本模块只负责置标志位 + st.rerun()：
  - pending_nav_to_programs（+ selected_program_id）—— 点击培养方案 chip
  - pending_nav_to_coop —— 点击 Co-op 的"去看看"
  - selected_course_id —— 点击入门推荐的查看（停留在搜索页）

Defensive by contract: every fetch is wrapped in try/except ApiError and a
failed endpoint silently drops its section — the landing must render even
when half the backend is warming. Program data shares program_view's
per-tab caches (_programs_cache / _curriculum_cache) so the landing and
the Programs page never double-fetch; the Co-op teaser keeps its own
_coop_teaser_cache (fetched once per tab, failure cached as [] like the
hero's _ready_info — a 30s timeout per rerun would freeze the landing).

防御性是硬性约定：每次抓取都包在 try/except ApiError 里，失败的端点会
悄悄丢弃自己的展示区块 —— 即使后端有一半还在预热，落地页也必须能渲染。
培养方案数据与 program_view 共用按标签页的缓存
（_programs_cache / _curriculum_cache），这样落地页和 Programs 页面
绝不会重复抓取；Co-op 预告区块保留自己的 _coop_teaser_cache（每个
标签页只抓一次，失败时缓存为 []，和 hero 的 _ready_info 一样 ——
否则每次 rerun 都等 30 秒超时会冻住整个落地页）。
"""

from __future__ import annotations

import html

# Featured programs for the 入门推荐 row, in display order. Ids missing
# from the seeded set silently drop out (checked against the /programs
# listing first, so unseeded ids never trigger per-rerun 404 fetches).
# 中文:入门推荐那一行的精选培养方案，按展示顺序排列。不在已 seed
# 集合里的 id 会被悄悄丢弃（先对照 /programs 列表检查一遍，未 seed 的
# id 就不会在每次 rerun 时都触发一次 404 请求）。
_FEATURED_PROGRAM_IDS: tuple[str, ...] = ("aai-ms", "cs-ms", "ds-ms")


def _semester1_pick(curriculum: dict) -> dict | None:
    """First semester-1 core/foundation course of a curriculum dict
    (the GET /programs/{id} shape), or None when the program has no
    semester-1 core/foundation entry. Pure dict logic — testable without
    Streamlit or a live API.

    某个课程表字典（GET /programs/{id} 的形状）里第一学期的核心/基础课，
    若该培养方案没有第一学期的核心/基础课条目则返回 None。纯字典逻辑
    —— 不需要 Streamlit 或真实 API 即可测试。"""
    for group in curriculum.get("semesters", []):
        if group.get("semester") != 1:
            continue
        for course in group.get("courses", []):
            if course.get("requirement_type") in ("core", "foundation"):
                return course
    return None


def _starter_card_html(*, code: str, name: str, prefix: str) -> str:
    """Compact 入门推荐 card: blue code + program pill + course name.
    紧凑的入门推荐卡片：蓝色代码 + 培养方案 pill + 课程名称。"""
    return (
        '<div class="nc-result-card">'
        f'<span class="nc-result-code">{html.escape(code)}</span> '
        f'<span class="nc-pill">{html.escape(prefix)}</span><br>'
        f'<span class="nc-result-name">{html.escape(name)}</span>'
        "</div>"
    )


def _render_program_row(st) -> None:
    """🎓 chips, one per seeded program — clicking hands off to the
    Programs page with that program pre-selected.

    🎓 chips，每个已 seed 的培养方案一个 —— 点击后交接给 Programs
    页面，并预先选中该培养方案。"""
    from app.api_client import ApiError  # noqa: PLC0415
    from app.program_view import get_programs_cached  # noqa: PLC0415

    try:
        programs = get_programs_cached(st)
    except ApiError:
        return
    if not programs:
        return

    st.markdown("**🎓 按培养方案浏览 / Browse by program:**")
    cols = st.columns(min(len(programs), 4))
    for i, p in enumerate(programs):
        label = f"{p.get('prefix', '?')} · {int(p.get('course_count', 0))} 门课"
        if cols[i % len(cols)].button(
            label, key=f"disc-prog-{p['program_id']}",
            use_container_width=True,
        ):
            st.session_state["selected_program_id"] = p["program_id"]
            st.session_state["pending_nav_to_programs"] = True
            st.rerun()


def _render_starter_row(st) -> None:
    """🔥 one semester-1 core/foundation course per featured program.
    Featured ids are validated against the /programs listing first so an
    unseeded id costs nothing (no 404 round-trip per rerun).

    🔥 每个精选培养方案各挑一门第一学期的核心/基础课。精选 id 会先对照
    /programs 列表校验，未 seed 的 id 因此零成本（不会每次 rerun 都
    发一次 404 往返）。"""
    from app.api_client import ApiError  # noqa: PLC0415
    from app.program_view import (  # noqa: PLC0415
        get_curriculum_cached,
        get_programs_cached,
    )

    try:
        available = {p["program_id"] for p in get_programs_cached(st)}
    except ApiError:
        return

    picks: list[tuple[str, dict]] = []  # (program prefix, course dict) / (培养方案前缀, 课程字典)
    for pid in _FEATURED_PROGRAM_IDS:
        if pid not in available:
            continue
        try:
            cur = get_curriculum_cached(st, pid)
        except ApiError:
            continue
        course = _semester1_pick(cur)
        if course:
            picks.append((str(cur.get("prefix", "")), course))
    if not picks:
        return

    st.markdown("**🔥 入门推荐 / Starter picks:**")
    cols = st.columns(len(picks))
    for col, (prefix, course) in zip(cols, picks):
        col.markdown(
            _starter_card_html(
                code=str(course.get("primary_code", "")),
                name=str(course.get("primary_name", "")),
                prefix=prefix,
            ),
            unsafe_allow_html=True,
        )
        if col.button(
            "查看", key=f"disc-course-{course['course_id']}",
            use_container_width=True,
        ):
            st.session_state["selected_course_id"] = course["course_id"]
            st.rerun()


def _render_coop_teaser(st) -> None:
    """💼 first two Co-op rows as one-liners + a hand-off button. Cached
    once per tab in _coop_teaser_cache; an ApiError caches [] (section
    hidden for this tab) — same degradation as the hero's _ready_info,
    because re-fetching a down endpoint on every rerun stalls the page.

    💼 展示最近两条 Co-op 记录的一句话摘要 + 一个跳转按钮。每个标签页
    在 _coop_teaser_cache 里缓存一次；ApiError 时缓存 []（本标签页隐藏
    该区块）—— 与 hero 的 _ready_info 采用同样的降级策略，因为每次
    rerun 都重新抓一个挂掉的端点会拖住整个页面。"""
    from app.api_client import ApiClient, ApiError  # noqa: PLC0415

    if "_coop_teaser_cache" not in st.session_state:
        try:
            with ApiClient(
                session_token=st.session_state.get("session_token"),
                timeout=5.0,
            ) as api:
                st.session_state["_coop_teaser_cache"] = api.list_coop()
        except ApiError:
            st.session_state["_coop_teaser_cache"] = []

    coops = st.session_state.get("_coop_teaser_cache") or []
    if not coops:
        return

    st.markdown("**💼 Co-op 风向 / Recent co-ops:**")
    for c in coops[:2]:
        # Markdown, not raw HTML — Streamlit sanitizes markdown itself
        # (same precedent as coop_view's listing rows).
        # 中文:用 markdown 而非原生 HTML —— Streamlit 会自行清理
        # markdown（与 coop_view 列表行的先例一致）。
        st.markdown(f"- **{c.get('company', '')}** · {c.get('role', '')}")
        if int(c.get("visibility_level", 0)) >= 1:
            st.caption("🔒 面试细节/薪资 · 贡献解锁")
    if st.button("去看看 →", key="disc-coop"):
        st.session_state["pending_nav_to_coop"] = True
        st.rerun()


def render_discover(st) -> None:
    """The discovery block. Caller (streamlit_app) shows it only when
    get_messages(...) is empty — once a conversation exists the chat
    history owns that space. Sections render independently; a dead
    endpoint drops its section without touching the others.

    发现区块本体。调用方（streamlit_app）只在 get_messages(...) 为空时
    展示它 —— 一旦对话存在，那块空间就归聊天历史所有。各区块独立渲染；
    某个端点挂了只会丢弃自己的区块，不影响其他区块。"""
    _render_program_row(st)
    _render_starter_row(st)
    _render_coop_teaser(st)


__all__ = ["render_discover"]
