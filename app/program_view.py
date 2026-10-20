"""Streamlit Program browser: 培养方案 card grid → per-semester curriculum.

Streamlit 培养方案浏览器：培养方案卡片网格 → 按学期分组的课程表。

Run:
    uv run streamlit run app/program_view.py

Surfaces the Layer 3 ontology head-on: pick a program, see its required
courses grouped by recommended semester, jump into any course's detail
panel. Until now this data only leaked out via /course/{id} program
context — students had no way to ask "show me the whole AAI plan".

直接呈现 Layer 3 本体：选一个培养方案，看它的必修课程按推荐学期分组，
点进任意课程的详情面板。在此之前，这份数据只能靠 /course/{id} 的
program context 零星露出 —— 学生没法直接问"把整个 AAI 培养方案给我看看"。

State contract (the main app owns navigation; this module only sets flags):
  - selected_program_id: which program's curriculum is open (None = grid).
  - pending_nav_to_search + selected_course_id: set when the user clicks
    查看 on a curriculum row — streamlit_app routes to the search page's
    detail panel on the next rerun. nav_page is NEVER touched here
    (writing a widget-bound key after the widget rendered raises
    StreamlitAPIException; see the filter-clear comment in streamlit_app).
  - _programs_cache / _curriculum_cache: per-tab response caches
    (underscore prefix = transient cache, not user state), kept by
    app.view_cache: a success is fetched again after 5 min, a failure is
    remembered for 30 s (so an outage does not make every rerun wait on the
    timeout) and then tried again. A refetch that changes a family's plans
    drops that family's plan choice (_PLAN_REVISED_KEY tells the page).

状态约定（导航由主 app 掌管；本模块只负责置标志位）：
  - selected_program_id：当前展开的是哪个培养方案的课程表（None = 网格）。
  - pending_nav_to_search + selected_course_id：用户在课程表某行点击
    查看时设置 —— streamlit_app 在下一次 rerun 时路由到搜索页的详情
    面板。这里绝不直接改 nav_page（组件渲染后再写其绑定的 key 会抛
    StreamlitAPIException；见 streamlit_app 中 filter-clear 处的说明）。
  - _programs_cache / _curriculum_cache：按标签页缓存的响应
    （下划线前缀 = 临时缓存，非用户状态），由 app.view_cache 维护：成功
    的结果 5 分钟后重新获取，失败记 30 秒（故障期间不会每次 rerun 都等
    超时），之后重试。重新获取后某个项目的方案变了，就清掉这个项目的
    方案选择（_PLAN_REVISED_KEY 告诉页面）。

The fetch helpers (get_programs_cached / get_curriculum_cached) are shared
with app.discover_view so the landing teasers and this page hit the same
cache instead of double-fetching per tab.

这两个抓取辅助函数（get_programs_cached / get_curriculum_cached）与
app.discover_view 共用，这样落地页的预览区和本页面命中同一份缓存，
而不是在同一个标签页里重复抓取两次。
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# === Shared fetch helpers (also imported by app.discover_view) ===
# 中文:共享的抓取辅助函数（app.discover_view 也会导入它们）


# Set to the program_id whose plan choice a refetch dropped; the curriculum view says so once.
# 中文：重新获取后清掉了哪个项目的方案选择，就记下它的 program_id；课程表页面提示一次。
_PLAN_REVISED_KEY = "_program_plan_revised"
PLAN_REVISED_NOTICE = "这个项目的版本化方案有更新，之前选的目录版本与路径已清除，请重新选择。"


def get_programs_cached(st) -> list[dict]:
    """GET /programs through the tab's view cache (_programs_cache; the list
    is public, the same for every viewer).

    Raises ApiError while a failure is fresh and nothing was loaded before —
    the program page renders st.error, the landing discovery block drops its
    section.

    经标签页的页面缓存（_programs_cache；列表是公开的，对每位访客都一样）
    取 GET /programs。

    失败仍有效、之前又没加载成功过时抛出 ApiError —— 培养方案页面据此
    渲染 st.error，落地页的发现区块则丢弃对应的展示区块。"""
    from app import view_cache  # noqa: PLC0415
    from app.api_client import ApiClient  # noqa: PLC0415

    def fetch() -> object:
        with ApiClient(
            session_token=st.session_state.get("session_token"), timeout=8.0,
        ) as api:
            return api.list_programs()

    return view_cache.cached(st.session_state, view_cache.PROGRAMS_KEY, fetch)


def get_curriculum_cached(st, program_id: str) -> dict:
    """GET /programs/{id} through the tab's view cache
    (_curriculum_cache[program_id]; public). Raises ApiError while a failure
    is fresh and no earlier success may be served: a definite answer such as
    404 (an unseeded id) always, a transient failure only when nothing was
    loaded before (view_cache.transient) — callers decide how loud to be.

    A refetch whose plans differ from the last ones loaded clears the family's
    plan choice, as the family refresh button below does: a changed revision
    must be chosen again, never silently kept. The choice is set to None, not popped:
    a popped key sends nothing to the browser, which keeps showing the old
    option and sends it back with the next rerun. Callers run this before the
    plan selectbox exists in the run (setting it afterwards would raise).

    经标签页的页面缓存（_curriculum_cache[program_id]；公开内容）取
    GET /programs/{id}。失败仍有效、又不能给出之前的成功结果时抛出 ApiError：
    明确的答复（例如未 seed 的 id 导致的 404）总是抛出，暂时性失败只在之前
    没加载成功过时抛出（view_cache.transient）—— 具体报错多响亮由调用方决定。

    重新获取到的方案和上次加载的不同时，清掉这个项目的方案选择，和下面的
    项目刷新按钮一样：版本变了就要重新选择，绝不悄悄沿用。选择是设成 None，而不是
    删掉：删掉的键不会通知浏览器，浏览器会继续显示旧选项，并在下一次 rerun
    时把它送回来。调用方都在这一轮的方案选择框创建之前调用（之后再设会报错）。"""
    from app import view_cache  # noqa: PLC0415
    from app.api_client import ApiClient  # noqa: PLC0415

    def fetch() -> object:
        with ApiClient(
            session_token=st.session_state.get("session_token"), timeout=8.0,
        ) as api:
            return api.get_program_curriculum(program_id)

    def drop_changed_choice(previous: object, current: object) -> None:
        key = f"program-plan-{program_id}"
        if st.session_state.get(key) is None:
            return  # Nothing chosen: Streamlit registers the selectbox's key with None.
        same = (isinstance(previous, dict) and isinstance(current, dict)
                and previous.get("plans") == current.get("plans"))
        if not same:
            st.session_state[key] = None
            st.session_state[_PLAN_REVISED_KEY] = program_id

    return view_cache.cached(
        view_cache.curricula(st.session_state), program_id, fetch, on_success=drop_changed_choice,
        state=st.session_state,
    )


# === Pure HTML builders (escaped and on one line — catalog names can contain & < ", and a blank
# line inside a value would end the HTML block, so the rest would be read as Markdown) ===
# 中文:纯 HTML 构造函数（转义并留在一行里 —— 目录里的名称可能含 & < 引号；值里的空行会结束 HTML
# 块，后面的内容就会被当成 Markdown）


def _program_card_html(*, prefix: str, full_name: str, course_count: int) -> str:
    """Program card: big blue prefix + full name + curriculum-size pill.
    The 查看课程表 button below it is a Streamlit widget (buttons can't
    live inside markdown HTML), so the card itself stays click-free.

    培养方案卡片：大号蓝色前缀 + 全名 + 课程数量 pill。下方的查看课程表
    按钮是一个 Streamlit 组件（按钮没法活在 markdown HTML 里面），所以
    卡片本体保持不可点击。"""
    from app.ui_theme import _one_line  # noqa: PLC0415

    return (
        '<div class="nc-card">'
        '<span style="color:#1677FF;font-weight:800;font-size:1.6rem;'
        f'letter-spacing:0.5px;">{_one_line(prefix)}</span>'
        f'<p class="nc-card-name">{_one_line(full_name)}</p>'
        f'<span class="nc-pill">{int(course_count)} 门课程</span>'
        "</div>"
    )


def _program_header_html(*, prefix: str, full_name: str) -> str:
    """Header card for the curriculum view (selected program).
    课程表视图（已选中培养方案）的头部卡片。"""
    from app.ui_theme import _one_line  # noqa: PLC0415

    return (
        '<div class="nc-card">'
        f'<span class="nc-card-code" style="font-size:1.35rem;">'
        f"{_one_line(prefix)}</span>"
        f'<p class="nc-card-name">{_one_line(full_name)}</p>'
        "</div>"
    )


def _semester_heading(semester: int | None) -> str:
    return (f"旧 seed：第 {semester} 学期建议（未核验）" if semester is not None
            else "未提供推荐学期（不等于任意学期都可修）")


def _course_row_html(
    *, code: str, name: str, requirement_type: str, notes: str | None,
) -> str:
    """One curriculum row: blue bold code + name + requirement badge
    (+ optional edge note). Badge comes from ui_theme.requirement_badge so
    the colors stay in lockstep with the course-detail panel — duplicating
    the core/foundation/elective_pool/capstone color table here would
    drift on the next palette pass.

    课程表的一行：蓝色加粗代码 + 名称 + 要求类型徽章（+ 可选的边注）。
    徽章来自 ui_theme.requirement_badge，这样配色才能与课程详情面板
    保持同步 —— 若在这里再复制一份 core/foundation/elective_pool/
    capstone 配色表，下次调色就会产生不一致。"""
    from app.ui_theme import _one_line, requirement_badge  # noqa: PLC0415

    note_html = ""
    if notes:
        note_html = (
            '<div style="color:#8A94A6;font-size:0.78rem;margin-top:2px;">'
            f"{_one_line(notes)}</div>"
        )
    return (
        '<div class="nc-result-card">'
        f'<span class="nc-result-code">{_one_line(code)}</span> '
        f'<span class="nc-result-name">{_one_line(name)}</span> '
        f"{requirement_badge(requirement_type)}"
        f"{note_html}"
        "</div>"
    )


# === Panels ===
# 中文:面板


def render_program_browser(st) -> None:
    """培养方案 browser panel. Caller owns page config / theme / auth
    chrome — same mounting contract as coop_view.render_coop_panel, so
    the main app can mount it as a nav page. Never lets ApiError escape:
    a down API degrades to st.error, not a stack trace.

    培养方案浏览面板。page config / 主题 / 认证 chrome 均由调用方负责 ——
    与 coop_view.render_coop_panel 遵循同一套挂载约定，主 app 才能把它
    当作一个导航页挂载。绝不让 ApiError 逃逸：API 挂掉时降级为
    st.error，而不是抛出堆栈跟踪。"""
    from app.api_client import ApiError  # noqa: PLC0415

    st.subheader("🎓 培养方案 · Programs")
    st.caption("版本化规则与旧 seed 分开浏览；规则展示不是个人选课资格审核")

    selected = st.session_state.get("selected_program_id")
    if selected:
        if st.button("← 所有培养方案", key="prog-back"):
            st.session_state.pop('_program_plan_link_pending', None)
            st.session_state["selected_program_id"] = None
            st.rerun()
        _render_curriculum(st, selected)
        return

    try:
        programs = get_programs_cached(st)
    except ApiError as e:
        st.error(f"无法加载培养方案列表: {e.detail}")
        return

    if not programs:
        st.info("还没有培养方案数据 — 运行 seed 脚本后刷新。")
        return

    cols = st.columns(2)
    for i, p in enumerate(programs):
        with cols[i % 2]:
            st.markdown(
                _program_card_html(
                    prefix=str(p.get("prefix", "")),
                    full_name=str(p.get("full_name", "")),
                    course_count=int(p.get("course_count", 0)),
                ),
                unsafe_allow_html=True,
            )
            st.caption(f"旧 seed 标签未核验 · 可用版本化规则 {int(p.get('plan_count', 0))} 份")
            if st.button(
                "查看课程表", key=f"prog-{p['program_id']}",
                use_container_width=True,
            ):
                st.session_state.pop('_program_plan_link_pending', None)
                st.session_state["selected_program_id"] = p["program_id"]
                st.rerun()


def _render_curriculum(st, program_id: str) -> None:
    """Per-semester course table for one program. 查看 buttons hand off to
    the SEARCH page's detail panel via pending_nav_to_search — the detail
    renderer (evidence bubbles, prereq rows) lives there and duplicating
    it here would fork the UI.

    某个培养方案按学期分组的课程表。查看按钮通过 pending_nav_to_search
    交接给搜索页的详情面板 —— 详情渲染逻辑（证据气泡、先修行）都在那边，
    在这里再复制一份会让 UI 分叉。"""
    from app.api_client import ApiError  # noqa: PLC0415

    # Refresh before rendering the bound scope widget. A changed revision
    # must be selected explicitly again; never silently reapply the old choice.
    # 中文：仅清除当前家族缓存与方案选择，不保存或复用政策响应。
    from app import view_cache  # noqa: PLC0415

    if st.button("刷新方案及政策证据", key=f"prog-refresh-{program_id}"):
        st.session_state.pop('_program_plan_link_pending', None)
        view_cache.curricula(st.session_state).pop(program_id, None)
        # Set, not popped, so the browser's selectbox is reset too (see get_curriculum_cached).
        st.session_state[f"program-plan-{program_id}"] = None
    try:
        cur = get_curriculum_cached(st, program_id)
    except ApiError as e:
        st.error(f"无法加载课程表: {e.detail}")
        return
    revised = st.session_state.get(_PLAN_REVISED_KEY) == program_id
    if revised:
        st.session_state.pop(_PLAN_REVISED_KEY, None)

    st.markdown(
        _program_header_html(
            prefix=str(cur.get("prefix", "")),
            full_name=str(cur.get("full_name", "")),
        ),
        unsafe_allow_html=True,
    )
    if cur.get("notes"):
        from app.text_render import literal_markdown  # noqa: PLC0415

        st.caption(literal_markdown(cur["notes"]))  # Database text: shown as written, not Markdown.
    from app.program_plan_view import render_program_plans  # noqa: PLC0415
    if revised:
        st.info(PLAN_REVISED_NOTICE)
    plan = render_program_plans(st, cur.get("plans", []), key=f"program-plan-{program_id}", program_id=program_id)
    if plan is not None:
        from app.program_policy_view import load_selected_program_policy_evidence  # noqa: PLC0415
        load_selected_program_policy_evidence(st, plan)
        if plan.review_status == "source_checked":
            from app.plan_draft_view import render_plan_draft  # noqa: PLC0415
            render_plan_draft(st, plan)
    st.caption("以下是旧 seed 的课程分类与学期建议，未经官方核验；校区/年度/路径未知。")

    # Share link (deep-link produce half). program_id is already the URL
    # form, so no ref normalization is needed here — unlike course codes,
    # which carry a space.
    # 分享链接（深链的生产半边）。program_id 本身就是 URL 形态，这里不需要
    # 做 ref 归一化 —— 不像课程代码那样含空格。
    from app.deep_links import share_url  # noqa: PLC0415
    from config import settings  # noqa: PLC0415

    with st.expander("🔗 分享这个培养方案 · Share"):
        st.code(
            share_url(settings.public_base_url, program=program_id,
                plan=plan if plan is not None and plan.review_status == 'source_checked' else None),
            language=None,
        )
        if plan is not None and plan.review_status == 'source_checked':
            st.caption('链接定位已选方案的完整范围和当前内容版本；不是个人适用性或资格证明。')
        else:
            st.caption('这里只分享项目入口，不携带方案年度／路径；对方仍需明确选择版本。')

    semesters = cur.get("semesters", [])
    if not semesters:
        st.info("该培养方案还没有课程数据。")
        return

    for group in semesters:
        sem = group.get("semester")
        st.markdown(f"**{_semester_heading(sem)}**")
        for c in group.get("courses", []):
            row_cols = st.columns([5, 1])
            row_cols[0].markdown(
                _course_row_html(
                    code=str(c.get("primary_code", "")),
                    name=str(c.get("primary_name", "")),
                    requirement_type=str(c.get("requirement_type", "")),
                    notes=c.get("notes"),
                ),
                unsafe_allow_html=True,
            )
            if row_cols[1].button(
                "查看", key=f"progcourse-{program_id}-{c['course_id']}",
                use_container_width=True,
            ):
                st.session_state["selected_course_id"] = c["course_id"]
                st.session_state["pending_nav_to_search"] = True
                st.rerun()


def render() -> None:
    """Standalone Program page (page config + theme + panel). The main app
    (streamlit_app) mounts render_program_browser directly instead.

    独立的 Program 页面（page config + 主题 + 面板）。主 app
    （streamlit_app）实际是直接挂载 render_program_browser，不走这条路径。"""
    import streamlit as st  # noqa: PLC0415

    from app.state_manager import init_state  # noqa: PLC0415
    from app.ui_theme import inject_theme  # noqa: PLC0415

    st.set_page_config(page_title="NEU-Compass · Programs", layout="wide")
    inject_theme(st)
    init_state(st.session_state)
    render_program_browser(st)


__all__ = [
    "get_curriculum_cached",
    "get_programs_cached",
    "render",
    "render_program_browser",
]


# `__main__` only: Streamlit sets the MAIN script's __name__ to "__main__",
# so `streamlit run app/program_view.py` works while imports from
# streamlit_app / tests never render (see the coop_view sys.argv bug note).
# 中文:仅 `__main__`：Streamlit 会把主脚本的 __name__ 设为 "__main__"，
# 所以 `streamlit run app/program_view.py` 能正常工作，而被
# streamlit_app / 测试导入时绝不会触发渲染（详见 coop_view 里 sys.argv
# 那个 bug 的说明）。
if __name__ == "__main__":
    render()
