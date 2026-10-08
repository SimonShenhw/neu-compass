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
failed endpoint drops its section — the landing must render even when half
the backend is warming — with one caption pointing at the sidebar's refresh
button. Program data shares program_view's per-tab caches so the landing and
the Programs page never double-fetch; the Co-op teaser has its own entry,
scoped to the viewer because the API redacts /coop by tier. All of them go
through app.view_cache: a failure is tried again 30 s later (not once per
rerun, which would make every rerun of an outage wait on the timeouts, and
not never, which hid recovered content for the rest of the tab).

防御性是硬性约定：每次抓取都包在 try/except ApiError 里，失败的端点会
丢弃自己的展示区块 —— 即使后端有一半还在预热，落地页也必须能渲染 ——
并用一行说明指向侧边栏的刷新按钮。培养方案数据与 program_view 共用按
标签页的缓存，这样落地页和 Programs 页面绝不会重复抓取；Co-op 预告区块
有自己的记录，并按访客区分范围，因为 API 按等级裁剪 /coop。它们都经过
app.view_cache：失败 30 秒后重试（不是每次 rerun 都重试——那样故障期间
每次 rerun 都要等超时；也不是永不重试——那样恢复后的内容在这个标签页里
一直藏着）。
"""

from __future__ import annotations

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
    """Compact 入门推荐 card: blue code + program pill + course name. The values come from the
    database, so they are escaped with line breaks turned into <br> (a blank line would end the
    HTML block). 中文：紧凑的入门推荐卡片：蓝色代码 + 培养方案 pill + 课程名称。值来自数据库，
    所以转义并把换行变成 <br>（空行会结束 HTML 块）。"""
    from app.ui_theme import plain_text_html  # noqa: PLC0415

    return (
        '<div class="nc-result-card">'
        f'<span class="nc-result-code">{plain_text_html(code)}</span> '
        f'<span class="nc-pill">{plain_text_html(prefix)}</span><br>'
        f'<span class="nc-result-name">{plain_text_html(name)}</span>'
        "</div>"
    )


def _render_program_row(st) -> bool:
    """🎓 chips, one per seeded program — clicking hands off to the
    Programs page with that program pre-selected. Returns True when the
    program list could not be loaded.

    🎓 chips，每个已 seed 的培养方案一个 —— 点击后交接给 Programs
    页面，并预先选中该培养方案。项目列表加载不了时返回 True。"""
    from app.api_client import ApiError  # noqa: PLC0415
    from app.program_view import get_programs_cached  # noqa: PLC0415

    try:
        programs = get_programs_cached(st)
    except ApiError:
        return True
    if not programs:
        return False

    st.markdown("**🎓 按培养方案浏览**")
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
    return False


def _render_starter_row(st) -> bool:
    """🔥 one semester-1 core/foundation course per featured program.
    Featured ids are validated against the /programs listing first so an
    unseeded id costs nothing (no 404 round-trip per rerun). Returns True
    when a list or curriculum it needed could not be loaded.

    🔥 每个精选培养方案各挑一门第一学期的核心/基础课。精选 id 会先对照
    /programs 列表校验，未 seed 的 id 因此零成本（不会每次 rerun 都
    发一次 404 往返）。需要的列表或课程表加载不了时返回 True。"""
    from app.api_client import ApiError  # noqa: PLC0415
    from app.program_view import (  # noqa: PLC0415
        get_curriculum_cached,
        get_programs_cached,
    )

    try:
        available = {p["program_id"] for p in get_programs_cached(st)}
    except ApiError:
        return True

    failed = False
    picks: list[tuple[str, dict]] = []  # (program prefix, course dict) / (培养方案前缀, 课程字典)
    for pid in _FEATURED_PROGRAM_IDS:
        if pid not in available:
            continue
        try:
            cur = get_curriculum_cached(st, pid)
        except ApiError:
            failed = True
            continue
        course = _semester1_pick(cur)
        if course:
            picks.append((str(cur.get("prefix", "")), course))
    if not picks:
        return failed

    st.markdown("**🔥 入门推荐**")
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
    return failed


def _render_coop_teaser(st) -> bool:
    """💼 first two Co-op rows as one-liners + a hand-off button. The
    listing is cached per tab under the viewer's scope (the API redacts
    /coop by tier, so a guest's or another account's listing is never
    reused after a login, logout or account switch); a failure hides the
    section and is tried again 30 s later. Returns True when the listing
    could not be loaded.

    💼 展示最近两条 Co-op 记录的一句话摘要 + 一个跳转按钮。列表按访客
    范围缓存在本标签页里（API 按等级裁剪 /coop，所以登录、登出或换账号
    之后，绝不会沿用游客或另一个账号的列表）；失败时隐藏该区块，30 秒后
    重试。列表加载不了时返回 True。"""
    from app import view_cache  # noqa: PLC0415
    from app.api_client import ApiClient, ApiError  # noqa: PLC0415

    # One read of the token for both the request and the scope it is stored under.
    # 中文：请求和存放范围用同一次读到的 token。
    token = st.session_state.get("session_token")

    def fetch() -> object:
        with ApiClient(session_token=token, timeout=5.0) as api:
            return api.list_coop()

    try:
        coops = view_cache.cached(
            st.session_state, view_cache.COOP_TEASER_KEY, fetch,
            scope=view_cache.viewer_scope({"session_token": token}),
        )
    except ApiError:
        return True
    if not isinstance(coops, list) or not coops:
        return False

    from app.ui_theme import plain_text_html  # noqa: PLC0415

    st.markdown("**💼 最近的 Co-op 经验**")
    for c in coops[:2]:
        # Company/role include reviewed student submissions. Escaped HTML, not Markdown:
        # Streamlit's Markdown keeps links of any scheme and other syntax.
        # 中文：公司和职位包含审核过的学生投稿。用转义后的 HTML 而不是 Markdown：
        # Streamlit 的 Markdown 会保留任意协议的链接和其他语法。
        st.markdown(
            f'<div class="nc-line">• <b>{plain_text_html(c.get("company", ""))}</b> · '
            f'{plain_text_html(c.get("role", ""))}</div>',
            unsafe_allow_html=True,
        )
        # visibility_level comes from what the row holds (schemas.coop.derive_visibility): 1 means
        # interview details and no salary, 2 means a salary range, with or without interview
        # details. The API leaves out what this viewer's tier has not unlocked, so only what the
        # level guarantees is claimed. 中文：visibility_level 由这一行的内容决定：1 是有面试细节、
        # 没有薪资，2 是有薪资区间（面试细节不一定有）。这位访客的等级还没解锁的字段 API 不会返回，
        # 所以只说这个等级保证有的内容。
        level = int(c.get("visibility_level", 0))
        locked = [label for label, holds, present in (
            ("面试细节", level == 1, c.get("interview_summary") or c.get("technical_questions")),
            ("薪资区间", level >= 2, c.get("salary_range_usd")),
        ) if holds and not present]
        if locked:
            st.caption(f"🔒 这条有{'和'.join(locked)}：你分享的经验公开后解锁")
    if st.button("去看看 →", key="disc-coop"):
        st.session_state["pending_nav_to_coop"] = True
        st.rerun()
    return False


# Shown once when any section could not be loaded. 中文：有区块加载不了时显示一次。
PARTIAL_NOTICE = "部分内容暂时没加载出来：稍后再操作页面时会重新获取，也可以点侧边栏的「🔄 刷新页面内容」。"


def render_discover(st) -> None:
    """The discovery block. Caller (streamlit_app) shows it only when
    get_messages(...) is empty — once a conversation exists the chat
    history owns that space. Sections render independently; a dead
    endpoint drops its section without touching the others, and one
    caption says that something is missing and how to fetch it again.

    发现区块本体。调用方（streamlit_app）只在 get_messages(...) 为空时
    展示它 —— 一旦对话存在，那块空间就归聊天历史所有。各区块独立渲染；
    某个端点挂了只会丢弃自己的区块，不影响其他区块，并用一行说明告诉
    用户少了内容、怎样重新获取。"""
    failed = [_render_program_row(st), _render_starter_row(st), _render_coop_teaser(st)]
    if any(failed):
        st.caption(PARTIAL_NOTICE)


__all__ = ["render_discover"]
