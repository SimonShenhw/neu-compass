"""Streamlit user UI: course search + course detail (PLAN v2.3 §3.7).

Streamlit 用户界面：课程搜索 + 课程详情（PLAN v2.3 §3.7）。

Production user-facing frontend until Andy Dong's `compass-frontend` (React)
repo lands. Streamlit is the canonical user surface in v0.x; team docs +
public URL `compass.neu-compass.me` point at it. The FastAPI backend (`api.*`)
is what Andy's React will call once that repo exists.

在 Andy Dong 的 `compass-frontend`（React）仓库落地之前，这里是面向用户的
生产前端。v0.x 阶段 Streamlit 是官方用户入口；团队文档与公网地址
`compass.neu-compass.me` 都指向它。FastAPI 后端（`api.*`）即是将来 React
要调用的那套接口。

Main Streamlit page: chat-style course search + course detail panel +
sample-query chips for first-time users + advanced-filter expander in
the sidebar.

Streamlit 主页面：对话式课程搜索 + 课程详情面板 + 首访用户的示例查询
chips + 侧边栏里的高级筛选折叠面板。

Run:
    uv run streamlit run app/streamlit_app.py

Layout:
    [ left: privacy notice + project selector + landing (before the first
      question only) + chat history ]
    [ right: selected course detail (app/course_detail_view.py) ]
    chat_input: main body, so Streamlit pins it to the bottom of the window
    sidebar: OAuth login/logout + advanced filters expander

布局：
    [ 左：隐私说明 + 项目选择 + 落地内容（仅在第一个问题之前）+ 聊天历史 ]
    [ 右：选中课程的详情（app/course_detail_view.py）]
    chat_input：放在主体里，Streamlit 会把它固定在窗口底部
    侧边栏：OAuth 登录/登出 + 高级筛选折叠面板

Pipeline per user message:
  1. add_message(role='user', content=prompt)
  2. ApiClient.chat_stream({"query": prompt, ...filters}) → NDJSON events
  3. meta event captured to state (drives evidence bubble)
  4. token events stream into render_streamed_answer — assistant message
     renders incrementally, link-filtered by answer_markdown
  5. Final assistant text + evidence persisted to state.messages

每条用户消息的处理流水线：
  1. add_message(role='user', content=prompt)
  2. ApiClient.chat_stream({"query": prompt, ...filters}) → NDJSON 事件流
  3. meta 事件写入 state（驱动证据气泡）
  4. token 事件流入 render_streamed_answer —— 助手消息增量渲染，链接经 answer_markdown 过滤
  5. 最终助手文本 + 证据持久化到 state.messages

Auth: login link / logout button live in the sidebar (render_auth_sidebar).
?code= callback handled at the top via handle_oauth_callback.

认证：登录链接 / 登出按钮位于侧边栏（render_auth_sidebar）。
?code= 回调在页面顶部由 handle_oauth_callback 处理。

PLAN §3.6 red lines: no API key in chat output, no commercial hooks,
OAuth restricted to NEU domains (server-side).

PLAN §3.6 红线：聊天输出中不得出现 API key、不得加商业化钩子、
OAuth 仅限 NEU 域名（服务端强制）。
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

# `streamlit run app/streamlit_app.py` executes this file as a top-level script,
# so the repo root must be on sys.path for `app.*` / `config` imports to resolve.
# `streamlit run` 会把本文件当作顶层脚本执行，须把仓库根目录加入 sys.path，
# `app.*` / `config` 这类绝对导入才能解析。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Windows consoles default to a legacy codepage (GBK on zh-CN); without forcing
# UTF-8, emoji/Chinese in printed output raise UnicodeEncodeError.
# Windows 控制台默认旧代码页（中文系统为 GBK），不强制 stdout 用 UTF-8 的话，
# 输出里的 emoji/中文会抛 UnicodeEncodeError。
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _format_evidence(results: list[dict]) -> list[dict]:
    """Keep identifiers, retrieval score, and source/gap metadata for history.
    中文：保留来源与缺失信息，不能在写入聊天历史时丢掉证据语义。"""
    return [
        {
            "course_id": r["course_id"],
            "primary_code": r["primary_code"],
            "primary_name": r["primary_name"],
            "score": r["score"],
            **({"answer_evidence": r["answer_evidence"]} if "answer_evidence" in r else {}),
        }
        for r in results
    ]


def _summarize_results(results: list[dict], matched_via: str) -> str:
    """Plain-text fallback summary used when Gemini stream unavailable.
    Gemini 流式输出不可用时使用的纯文本降级摘要。"""
    if not results:
        return "No matching courses. Try different terms or relax filters."
    if matched_via == "alias":
        r = results[0]
        return (
            f"**{r['primary_code']} — {r['primary_name']}** "
            f"(direct alias match)"
        )
    lines = [f"Top {len(results)} matches:"]
    for i, r in enumerate(results, 1):
        lines.append(
            f"{i}. **{r['primary_code']} — {r['primary_name']}** "
            f"(score {r['score']:.3f})"
        )
    return "\n\n".join(lines)


def stream_assistant(
    api: Any,
    body: dict[str, Any],
    state: Any,
) -> Iterator[str]:
    """Generator for `render_streamed_answer`. Consumes /chat NDJSON events,
    yields assistant tokens, and side-effect captures the meta event in
    `state['last_chat_meta']` for the post-stream evidence rendering.

    供 `render_streamed_answer` 使用的生成器：消费 /chat 的 NDJSON 事件流，逐个
    产出助手 token，并把 meta 事件旁路存入 `state['last_chat_meta']`，
    供流结束后渲染证据区使用。

    On in-stream error event, yields a user-facing warning + stops. On
    'done', stops. Pure logic; no Streamlit imports.

    流中收到 error 事件时，先产出一条面向用户的警告再停止；收到 'done'
    即停止。纯逻辑，不导入 Streamlit。
    """
    state["last_chat_meta"] = None
    state["last_chat_error"] = None
    state['last_chat_feedback'] = None
    import hashlib
    answer_hash = hashlib.sha256()
    sent_text = False
    for event in api.chat_stream(body):
        etype = event.get("type")
        if etype == "meta":
            state["last_chat_meta"] = event
        elif etype == "token":
            text = event.get("text", "")
            if text:
                answer_hash.update(text.encode('utf-8'))
                sent_text = True
                yield text
        elif etype == "error":
            detail = event.get("detail", "unknown error")
            state["last_chat_error"] = detail
            # The blank line only separates the notice from text; with no text the stored turn
            # (sent back as history) would start with it. 中文：空行只用来和前面的文字隔开；
            # 没有文字时，存下的这一轮（会作为历史再发回去）会以空行开头。
            yield f"\n\n⚠️ {detail}" if sent_text else f"⚠️ {detail}"
            return
        elif etype == "done":
            if body.get('allow_feedback_capture') is not True:
                return
            from config import settings  # noqa: PLC0415
            if settings.answer_feedback_enabled is not True:
                return
            from schemas.answer_feedback import AnswerFeedbackReceipt
            try:
                target = AnswerFeedbackReceipt.model_validate(event.get('feedback'))
                if state['last_chat_meta'] is not None and target.answer_sha256 == answer_hash.hexdigest():
                    state['last_chat_feedback'] = target.model_dump(mode='json')
            except ValueError:
                pass
            return


def _render_message_text(st: Any, msg: dict) -> None:
    """Assistant text is model output, so only official catalog links stay
    clickable; the student's own text renders as typed.

    助手文本是模型输出，只有官方目录链接保持可点击；学生自己输入的文本原样渲染。"""
    from app.answer_evidence_view import answer_markdown  # noqa: PLC0415

    content = str(msg["content"])
    st.markdown(answer_markdown(content) if msg["role"] == "assistant" else content)


from app.chat_view import _context_course_ids, _recent_history  # noqa: E402 - compat exports; needs sys.path above


FOLLOWUP_CHIPS_SINGLE: list[str] = [
    "这门课讲什么内容？",
    "这门课作业量大吗？",
    "先修要求是什么？",
]
FOLLOWUP_CHIPS_MULTI: list[str] = [
    "这几门课怎么选？",
    "哪门最适合零基础？",
    "第一门的先修要求？",
]
"""Suggested follow-up chips under the latest answer. Click → injected
via pending_query, riding the same conversation-continuity path the
typed version would take.

最新回答下方的追问建议 chips。点击后经 pending_query 注入，与手动输入
一样，走同一条对话连续性路径。"""


SAMPLE_QUERIES: list[tuple[str, str]] = [
    ("📘 CS 5800", "CS 5800"),
    ("🤖 适合入门的 AI 选修课", "easy AI elective for ML beginner"),
    ("📊 数据库方向的课", "database management systems"),
    ("⚖️ 课业最轻的 ML 课", "lightest workload ML class"),
]
"""Hero-block sample chips. Shown only on first visit (no chat history yet).
Two languages because the audience is bilingual NEU graduate students;
clicking a chip injects the query string verbatim into the chat pipeline.

Hero 区示例查询 chips，仅在首次访问（尚无聊天历史）时展示。之所以中英
双语，是因为受众是中英双语的 NEU 研究生；点击 chip 会把查询串原样注入
聊天流水线。"""


def _render_evidence_block(st: object, results: list[dict], key_prefix: str) -> None:
    """Result cards for one evidence list: rank + code + name + relative
    score bar, with a 查看 button per row. Bar widths normalize against
    the top score WITHIN this list (relative retrieval score, NOT factual confidence).
    Shared by chat history and the live response path so the two can't
    drift apart visually.

    渲染一组证据的结果卡片：名次 + 课程代码 + 名称 + 相对分数条，每行带
    一个查看按钮。分数条宽度按本列表内的最高分归一化（相对检索分数，
    不是事实可信度）。聊天历史与实时响应两条路径共用此函数，两处的视觉
    呈现才不会各自漂移。"""
    from app.state_manager import select_course  # noqa: PLC0415
    from app.ui_theme import result_card_html  # noqa: PLC0415
    from app.answer_evidence_view import render_answer_evidence  # noqa: PLC0415

    top = max((float(r.get("score", 0.0)) for r in results), default=0.0)
    for i, ev in enumerate(results):
        score = float(ev.get("score", 0.0))
        pct = int(round(100 * score / top)) if top > 0 else 50
        cols = st.columns([5, 1])
        cols[0].markdown(
            result_card_html(
                rank=i + 1,
                code=ev["primary_code"],
                name=ev["primary_name"],
                score=score,
                pct=max(pct, 8),  # keep a visible sliver for low scores / 低分也保留可见细条
            ),
            unsafe_allow_html=True,
        )
        render_answer_evidence(cols[0], ev.get("answer_evidence"))
        if cols[1].button(
            "查看", key=f"{key_prefix}-{ev['course_id']}",
            use_container_width=True,
        ):
            select_course(st.session_state, ev["course_id"])
            st.rerun()


def _render_filters_sidebar(st: object, state: object) -> dict[str, object]:
    """Sidebar 'Advanced filters' expander. Returns the active filters dict
    (already in session_state, returned for convenience). No-side-effect read.

    侧边栏「高级筛选」折叠面板。返回当前生效的 filters 字典（其实已存于
    session_state，返回只是方便调用方）。读取无副作用。
    """
    with st.sidebar:
        st.divider()
        with st.expander("🎯 Advanced filters", expanded=False):
            filters: dict[str, object] = state.get("filters", {}) or {}

            # Only CREDITS is offered. Term / delivery_mode / professor
            # filters exist in the API but their source data is absent
            # catalog-wide (2026-06 data review: term & delivery_mode
            # 0/6,469, professor ~3 courses) — exposing them meant every
            # use returned an empty result set. Re-enable each one when a
            # pipeline actually populates it (syllabus ingestion for term
            # /mode, RMP enrichment for professor).
            # 只开放 CREDITS 一项。term / delivery_mode / professor 过滤在
            # API 里存在，但全目录范围源数据缺失（2026-06 数据盘点：term 与
            # delivery_mode 为 0/6,469，professor 仅约 3 门课）——一旦开放，
            # 用一次就是一次空结果。等相应管线真正填充数据后再逐项恢复
            # （term/mode 靠 syllabus 摄取，professor 靠 RMP 增强）。
            credits_str = st.text_input(
                "Credits", value=str(filters.get("credits") or ""),
                placeholder="3", key="filter_credits",
            )

            try:
                credits_v = int(credits_str) if credits_str else None
            except ValueError:
                st.caption("⚠️ Credits must be a number 0-12")
                credits_v = None

            new_filters: dict[str, object] = {
                "credits": credits_v,
            }
            state["filters"] = new_filters

            active = sum(1 for v in new_filters.values() if v not in (None, ""))
            if active:
                st.caption(f"✓ {active} filter{'s' if active > 1 else ''} active")
                # Use on_click rather than mutating state inside the if-block.
                # Streamlit raises StreamlitAPIException if you set
                # st.session_state[<widget_key>] AFTER the widget has been
                # instantiated this render — and the four filter widgets
                # above this button were already created. on_click runs as
                # a callback BEFORE the next rerun, while mutation is legal.
                # `pop` (vs setting "") is what the docs recommend for
                # clearing widget-bound state cleanly.
                # 用 on_click 回调而不是在 if 块里直接改 state：本轮渲染中
                # 组件实例化之后再写 st.session_state[<widget_key>] 会抛
                # StreamlitAPIException —— 而此按钮上方的筛选组件已经创建。
                # on_click 在下一次 rerun 之前的回调阶段执行，那时改写才
                # 合法。用 `pop`（而非置 ""）清理组件绑定状态是官方文档的
                # 推荐做法。
                st.button(
                    "Clear all",
                    use_container_width=True,
                    key="filter_clear",
                    on_click=_clear_filters_callback,
                )
    return state.get("filters", {})


def _clear_filters_callback() -> None:
    """on_click callback for the 'Clear all' filter button. Runs in the
    callback phase, so mutating widget-bound session_state keys is allowed
    (the alternative — setting state[k]="" inline after the widgets render
    — raises StreamlitAPIException). Caller should not import streamlit
    at module top to keep test imports cheap; lazy import here.

    「Clear all」筛选按钮的 on_click 回调。它运行在回调阶段，因此允许改写
    组件绑定的 session_state 键（另一种写法 —— 组件渲染后内联置
    state[k]="" —— 会抛 StreamlitAPIException）。为了让测试导入保持轻量，
    模块顶层不导入 streamlit，这里用惰性导入。"""
    import streamlit as st  # noqa: PLC0415
    st.session_state["filters"] = {}
    st.session_state.pop("filter_credits", None)


def _refresh_view_cache_callback() -> None:
    """on_click callback for the sidebar's refresh button: the read-only page caches (app.view_cache)
    fetch again on their next read. The callback itself leaves chat history, pending questions and
    widget choices as they are; the refetch it causes clears a family's plan choice only when that
    family's plans changed (program_view.get_curriculum_cached).
    中文：侧边栏刷新按钮的 on_click 回调：只读页面缓存（app.view_cache）下一次读取时重新获取。回调
    本身不动聊天历史、待发的问题和各组件的选择；它引起的重新获取只在某个项目的方案变了时清除该项目的
    方案选择（program_view.get_curriculum_cached）。"""
    import streamlit as st  # noqa: PLC0415

    from app.view_cache import expire_all  # noqa: PLC0415

    expire_all(st.session_state)


# Under the sidebar's refresh button when a read of this run showed the content loaded earlier because
# fetching it again failed (app.view_cache.served_fallback), so a failed refresh is not silent.
# 中文：本次运行里有读取因为重新获取失败而显示了之前加载的内容时，显示在侧边栏刷新按钮下面
# （app.view_cache.served_fallback），刷新失败时不再悄无声息。
FALLBACK_NOTICE = "有些内容这次没能更新，显示的是上次加载的版本；稍后再操作页面时会再试。"


def _end_page(st, notice_slot) -> None:
    """End of every page: FALLBACK_NOTICE in the sidebar slot when it applies, then the footer.
    Runs after the page's own cached reads, so the notice is about this run.
    中文：每个页面的结尾：适用时在侧边栏的位置显示 FALLBACK_NOTICE，然后是页脚。它在页面自己的缓存
    读取之后运行，所以说明针对的是这一次运行。"""
    from app import view_cache  # noqa: PLC0415
    from app.ui_theme import footer_html  # noqa: PLC0415

    if view_cache.served_fallback(st.session_state):
        notice_slot.caption(FALLBACK_NOTICE)
    st.markdown(footer_html(), unsafe_allow_html=True)


def render() -> None:
    """Render the chat UI. Imported lazily so `import app.streamlit_app`
    in tests doesn't trigger Streamlit's session machinery.

    渲染聊天 UI。内部依赖全部惰性导入，测试里 `import app.streamlit_app`
    不会触发 Streamlit 的会话机制。"""
    import streamlit as st  # noqa: PLC0415

    from app.api_client import ApiClient, ApiError  # noqa: PLC0415
    from app.state_manager import (  # noqa: PLC0415
        add_message,
        get_messages,
        init_state,
        is_logged_in,
        keep_choices,
        record_search,
    )
    from app.streamlit_auth_ui import (  # noqa: PLC0415
        handle_oauth_callback,
        render_auth_sidebar,
    )
    from app.ui_theme import (  # noqa: PLC0415
        guest_banner_html,
        hero_html,
        inject_theme,
        matched_via_badge,
        sidebar_brand_html,
    )

    st.set_page_config(
        page_title="NEU-Compass · Course Search",
        page_icon="🧭",
        layout="wide",
    )
    inject_theme(st)
    init_state(st.session_state)
    keep_choices(st.session_state)  # Before any widget of this run. 中文：在这一轮的任何组件之前。
    from app import view_cache  # noqa: PLC0415

    view_cache.begin_run(st.session_state)  # Before any cached read of this run.

    # Process ?code= callback BEFORE rendering anything else (it may rerun).
    # 先处理 ?code= 回调再渲染其他内容（回调可能触发 rerun）。
    handle_oauth_callback()

    # Cookie session (refresh-survival): restore first so a failed restore
    # can queue a cookie clear, then flush — the flush also renders writes
    # queued by the OAuth callback on the previous pass, or by the logout
    # button's callback just before this run.
    # Cookie 会话（刷新不掉线）：先恢复登录，这样失败的恢复能把「清 cookie」
    # 排入队列；随后统一 flush —— flush 同时会把上一轮 OAuth 回调、或者
    # 这一轮之前登出按钮回调排队的写操作真正下发给浏览器。
    from app.cookie_session import (  # noqa: PLC0415
        flush_pending_cookie,
        restore_login_from_cookie,
    )

    restore_login_from_cookie()
    flush_pending_cookie()

    st.sidebar.markdown(sidebar_brand_html(), unsafe_allow_html=True)
    render_auth_sidebar()
    active_filters = _render_filters_sidebar(st, st.session_state)

    # Corpus size for the hero pill, from /ready through the tab's view cache (app.view_cache): a
    # failure (503 while the API warms up) shows the number-free wording in hero_html and is tried
    # again 30 s later instead of for the rest of the tab, and a success is fetched again after 5 min.
    # 中文：hero 徽标里的课程总数，经标签页的页面缓存（app.view_cache）取 /ready：失败（API 预热时的
    # 503）显示 hero_html 里不带数字的文案，30 秒后重试，而不是整个标签页都不再取；成功的结果 5 分钟后
    # 重新获取。
    def _fetch_ready() -> object:
        with ApiClient(timeout=5.0) as api:
            return api.ready()

    try:
        ready_info = view_cache.cached(st.session_state, view_cache.READY_KEY, _fetch_ready)
    except ApiError:
        ready_info = {}
    if not isinstance(ready_info, dict):
        ready_info = {}

    logged_in = is_logged_in(st.session_state)
    st.markdown(
        hero_html(
            logged_in=logged_in,
            display_name=st.session_state.get("user_display_name") or "",
            courses_indexed=ready_info.get("courses_indexed"),
        ),
        unsafe_allow_html=True,
    )

    # Sidebar nav (not st.tabs): chat_input must stay bottom-pinned on the
    # search page, which tabs would break. Pages: search / programs / co-op.
    # 侧边栏导航（不用 st.tabs）：搜索页的 chat_input 必须固定在页面底部，
    # tabs 会破坏这一点。页面：搜索 / 培养方案 / Co-op。
    # New pages go at the end so the earlier indices (deep links, pending_nav_*) keep their meaning.
    # 中文：新页面加在末尾，前面页面的序号（深链、pending_nav_*）不变。
    pages = ["🔍 课程搜索 · Search", "🎓 培养方案 · Programs", "💼 Co-op 经验", "⚖️ 课程对比 · Compare",
             "🔒 数据与隐私 · Privacy"]

    # Cross-page hand-offs (discover chips, curriculum 查看 buttons) queue
    # a pending_nav_* flag + st.rerun(); we consume it HERE, before the
    # radio instantiates — writing a widget-bound key after the widget
    # rendered raises StreamlitAPIException (see filter-clear note).
    # 跨页面跳转（发现区 chips、课程表查看按钮）先写入 pending_nav_* 标志再
    # st.rerun()；必须在 radio 实例化之前、也就是这里消费掉 —— 组件渲染后
    # 再写其绑定键会抛 StreamlitAPIException（见 filter-clear 处的说明）。
    if st.session_state.pop("pending_nav_to_programs", None):
        st.session_state["nav_page"] = pages[1]
    if st.session_state.pop("pending_nav_to_coop", None):
        st.session_state["nav_page"] = pages[2]
    if st.session_state.pop("pending_nav_to_search", None):
        st.session_state["nav_page"] = pages[0]

    # Deep links (?course= / ?program=) route the same way, and must land in
    # this same window: after handle_oauth_callback (which clears
    # query_params when processing an OAuth return) and before the radio instantiates.
    # 深链（?course= / ?program=）走同一套路由，且必须落在同一个窗口里：
    # 在 handle_oauth_callback 之后（它处理 OAuth 回调时会清空 query_params），
    # 在 radio 实例化之前。
    from app.deep_links import apply_deep_link  # noqa: PLC0415

    apply_deep_link(st, pages=pages)

    nav = st.sidebar.radio("页面 / Pages", pages, key="nav_page")
    # The callback runs before the next script run, so every cached read of that run fetches again
    # (the hero above included). Reruns never repeat a question, a Co-op submission or a vote.
    # 中文：回调在下一次脚本运行之前执行，所以那一次运行里每个缓存读取都会重新获取（包括上面的
    # hero）。rerun 不会重发提问、Co-op 投稿或评价。
    st.sidebar.button(
        view_cache.REFRESH_LABEL, key="view_cache_refresh", on_click=_refresh_view_cache_callback,
        use_container_width=True,
        help="重新获取课程总数、培养方案和 Co-op 预览；不会重新发送提问、投稿或评价。",
    )
    # Filled by _end_page once the page's cached reads have run. 中文：页面的缓存读取都跑完后由 _end_page 填写。
    fallback_slot = st.sidebar.empty()
    # Guests see the Co-op tier summary under the hero on every page except Co-op itself, whose
    # own notice says the same thing. 中文：游客在除 Co-op 页以外的每个页面都会在 hero 下面看到
    # Co-op 分级说明；Co-op 页自己的提示内容相同，不再重复。
    if not logged_in and not nav.startswith("💼"):
        st.markdown(guest_banner_html(), unsafe_allow_html=True)
    if nav.startswith("🎓"):
        from app.program_view import render_program_browser  # noqa: PLC0415

        render_program_browser(st)
        _end_page(st, fallback_slot)
        return
    if nav.startswith("💼"):
        from app.coop_view import render_coop_panel  # noqa: PLC0415

        render_coop_panel(st)
        _end_page(st, fallback_slot)
        return

    if nav.startswith("⚖️"):
        from app.compare_view import render_compare_page  # noqa: PLC0415

        render_compare_page(st)
        _end_page(st, fallback_slot)
        return

    if nav.startswith("🔒"):
        from app.privacy_view import render_privacy_page  # noqa: PLC0415

        render_privacy_page(st)
        _end_page(st, fallback_slot)
        return

    # 5:3 (was 3:2): the chat stream is the primary surface — review
    # feedback flagged ~35% wasted horizontal space with the old ratio.
    # 5:3（原 3:2）：聊天流才是主界面 —— 评审反馈指出旧比例约有 35% 的
    # 横向空间被浪费。
    chat_col, detail_col = st.columns([5, 3])

    with chat_col:
        st.subheader("💬 提问")
        # Privacy notice (and the optional save permission) BEFORE the input, at the top of the
        # chat column: the input itself is pinned to the bottom of the window (06C-1).
        # 中文：隐私说明（以及可选的保存许可）放在输入框之前、聊天列顶部：输入框本身固定在窗口
        # 底部（06C-1）。
        from app.answer_feedback_view import render_feedback_capture_control  # noqa: PLC0415
        capture_allowed = render_feedback_capture_control(st)
        from app.program_plan_view import render_chat_program_selector  # noqa: PLC0415
        from app.program_view import get_programs_cached  # noqa: PLC0415
        try:
            chat_program_id = render_chat_program_selector(st, get_programs_cached(st))
        except ApiError:
            chat_program_id = None
            st.caption("暂时无法加载项目列表；课程搜索仍可使用。")
        from app.chat_plan_view import render_chat_plan_selector  # noqa: PLC0415
        chat_plan = render_chat_plan_selector(st, chat_program_id)

    # In the main body, not inside a column: Streamlit pins a main-body chat_input to the bottom
    # of the window. Inside chat_col it rendered inline after the landing content, about 2.5
    # screens down on a 375×812 phone (measured 2026-10-06).
    # 中文：放在主体里，不放进列：Streamlit 会把主体里的 chat_input 固定在窗口底部。放在
    # chat_col 里时它跟在落地内容后面，在 375×812 的手机上要往下翻约 2.5 屏（2026-10-06 实测）。
    chat_input_value = st.chat_input(
        "问任何课程问题：CS 5800 / 适合入门的 ML 课 / algo …"
    )
    pending_query = st.session_state.pop("pending_query", None)
    prompt = chat_input_value or pending_query

    with chat_col:
        # Discovery + sample chips — only before the first question, and not while that first
        # question is streaming (the answer would otherwise appear below all of it). Round-3
        # fix for the cold-start blank screen: the landing offers browsable CONTENT
        # (programs / starter courses / co-op teaser), not just example queries.
        # 发现区 + 示例 chips —— 只在第一个问题之前显示，第一个问题正在回答时也不显示（否则
        # 回答会出现在这些内容下面）。第三轮针对冷启动白屏的修复：落地页提供可浏览的真实内容
        # （培养方案 / 入门课程 / Co-op 预览），而不只是示例查询。
        if not get_messages(st.session_state) and not prompt:
            from app.discover_view import render_landing  # noqa: PLC0415

            render_landing(st, SAMPLE_QUERIES)

        # Resolve legacy hooks here, inside the chat column, at each script run.
        # 中文：聊天列内查找主入口原有 renderer，替换点和位置不变。
        from app.chat_view import render_chat_history  # noqa: PLC0415

        render_chat_history(
            st, get_messages(st.session_state),
            render_message_text=_render_message_text,
            render_evidence_block=_render_evidence_block,
            matched_via_badge=matched_via_badge,
            single_chips=FOLLOWUP_CHIPS_SINGLE,
            multi_chips=FOLLOWUP_CHIPS_MULTI,
        )

        # New input → stream assistant response. Two paths: the pinned chat_input box OR a
        # pending_query injected by a sample / follow-up chip (both read above).
        if prompt:
            # Continuity payload BEFORE the new prompt joins the history:
            # history = prior turns (the new question travels as `query`),
            # context ids = the previous answer's evidence (follow-up
            # referent set for the API's context tier).
            prior_messages = get_messages(st.session_state)
            chat_history = _recent_history(prior_messages)
            context_ids = _context_course_ids(prior_messages)

            add_message(st.session_state, role="user", content=prompt)
            with st.chat_message("user", avatar="🎓"):
                st.markdown(prompt)

            chat_body: dict[str, object] = {
                "query": prompt,
                "k": min(st.session_state.get("search_k", 5), 10),
                "allow_feedback_capture": capture_allowed,
            }
            if chat_program_id is not None:
                chat_body["program_id"] = chat_program_id
            if chat_plan is not None:
                chat_body["plan"] = chat_plan.model_dump(mode="json")
            if chat_history:
                chat_body["history"] = chat_history
            if context_ids:
                chat_body["context_course_ids"] = context_ids
            # Propagate sidebar filters to the chat request — this is what
            # surfaces the backend's term / credits / delivery_mode / professor
            # filtering capability that was previously inaccessible from UI.
            # NB: 0 is a VALID credits value (0-credit seminars/co-ops exist);
            # only None/"" mean "filter not set".
            for fk, fv in (active_filters or {}).items():
                if fv is not None and fv != "":
                    chat_body[fk] = fv
            with st.chat_message("assistant", avatar="🧭"):
                final_text = ""
                try:
                    with ApiClient(
                        session_token=st.session_state.get("session_token")
                    ) as api:
                        from app.answer_evidence_view import render_streamed_answer  # noqa: PLC0415

                        stream = stream_assistant(api, chat_body, st.session_state)
                        final_text = render_streamed_answer(st, stream)
                except ApiError as e:
                    if e.status_code == 409:
                        from app.chat_plan_view import queue_chat_plan_reset  # noqa: PLC0415
                        queue_chat_plan_reset(st.session_state, chat_program_id, e.detail)
                    # 409 = the API needs the student to clarify the program
                    # (ambiguous prefix / selection conflict), not a failure.
                    # 中文：409 表示需要学生明确项目（前缀歧义或选择冲突），不是故障。
                    final_text = (
                        f"🧭 {e.detail}" if e.status_code == 409
                        else f"⚠️ Chat failed: {e.detail}"
                    )
                    # Same filter as when history re-renders this assistant message.
                    # 中文：和历史里重新渲染这条助手消息时用同一个过滤。
                    from app.answer_evidence_view import answer_markdown  # noqa: PLC0415

                    st.markdown(answer_markdown(final_text))

                meta = st.session_state.get("last_chat_meta") or {}
                results = meta.get("results", [])
                matched_via = meta.get("matched_via", "empty")
                if meta.get("plan_context") is not None:
                    from app.chat_plan_view import render_plan_context  # noqa: PLC0415
                    with st.expander("📘 所选方案与课程位置"):
                        render_plan_context(st, meta["plan_context"], results)
                if results:
                    record_search(
                        st.session_state,
                        query=prompt,
                        results=results,
                        matched_via=matched_via,
                    )
                    n_live = len(results)
                    with st.expander(f"📎 相关课程（{n_live} 门）"):
                        st.markdown(
                            matched_via_badge(matched_via),
                            unsafe_allow_html=True,
                        )
                        _render_evidence_block(
                            st, results, key_prefix="open-live",
                        )

            add_message(
                st.session_state,
                role="assistant",
                content=final_text,
                evidence=_format_evidence(results),
                matched_via=matched_via,
                feedback=st.session_state.get('last_chat_feedback'),
                notices=meta.get("notices"),
                plan_context=meta.get("plan_context"),
            )
            # Rerun immediately so the message renders via the HISTORY path.
            # The live evidence block above only exists inside `if prompt:`;
            # on the rerun a 查看 click triggers, prompt is None, so those
            # `open-live-*` widgets are never re-instantiated and Streamlit
            # silently DROPS the click — the buttons were dead. History keys
            # are stable across reruns, so clicks work there.
            st.rerun()

    with detail_col:
        from app.course_detail_view import render_selected_course  # noqa: PLC0415

        render_selected_course(st)

    _end_page(st, fallback_slot)


# Streamlit entry point: render() at module top when running via streamlit
# (which sets the main script's __name__ to "__main__"). Plain __main__
# guard so importing this module (tests, other pages) never renders — the
# old `"streamlit" in sys.argv[0]` clause made ANY import under a running
# streamlit process execute render() at import time (see coop_view bug).
if __name__ == "__main__":
    render()
