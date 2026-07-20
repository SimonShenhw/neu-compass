"""Graphviz DOT builder for the course-prerequisite mini-graph.

The course-detail panel lists prereqs as flat rows; a two-level graph
reads faster once a course has 3+ edges ("what feeds into this, what does
it unlock"). st.graphviz_chart consumes a DOT source string directly, so
this stays a PURE string builder — no graphviz import, no Streamlit
import — testable with plain assertions like the ui_theme builders.

课程详情面板把先修课列成平铺的行;当一门课有 3+ 条边时("这门课的输入
是什么,它又解锁了什么"),两层图读起来更快。st.graphviz_chart 直接吃
一个 DOT 源字符串,所以这里保持为一个纯字符串构建器 —— 不 import
graphviz,也不 import Streamlit —— 可以像 ui_theme 的构建器一样用普通
断言测试。

Visual language mirrors the Alipay theme (app/ui_theme.py): center course
solid #1677FF with white text, prereqs light blue #E8F1FF, dependents
neutral gray. Edge style encodes the requirement tier — required=solid,
recommended=dashed, concurrent=dotted — the same vocabulary as
schemas.program.PrereqRequirement, with the raw value as the edge label.

视觉语言与 Alipay 主题(app/ui_theme.py)保持一致:中心课程用实心
#1677FF 配白字,先修课用浅蓝 #E8F1FF,后续课用中性灰。边的样式编码了
requirement 的等级 —— required=实线,recommended=虚线,concurrent=点线
—— 与 schemas.program.PrereqRequirement 用词一致,原始值作为边的标签。

Layout: rankdir=TB with every prereq node pinned in a rank=min subgraph,
so prereqs sit on top and arrows flow DOWN into the course, then down
again to dependents. That matches how students read the relationship
("take A, then B") — rankdir=BT draws the same shape but flips the
arrow-reading order.

布局:rankdir=TB,每个先修课节点都被钉在一个 rank=min 子图里,这样
先修课排在最上面,箭头先向下流入本课程,再向下流到后续课程。这与学生
阅读这种关系的方式一致("先修 A,再修 B")—— rankdir=BT 画出来形状
相同,但箭头的阅读顺序会反过来。
"""

from __future__ import annotations

ALIPAY_BLUE = "#1677FF"

# requirement → DOT edge style. Unknown values degrade to solid (drawn,
# just unstyled) rather than crashing the chart on a future tier.
# 中文:requirement → DOT 边样式的映射。未知值会降级为 solid(照样画
# 出来,只是没有特殊样式),而不是在未来出现新等级时让图表崩溃。
_EDGE_STYLE: dict[str, str] = {
    "required": "solid",
    "recommended": "dashed",
    "concurrent": "dotted",
}


def _q(label: str) -> str:
    """DOT double-quoted string. Embedded double quotes get escaped —
    catalog course names can legally contain them, and one unescaped
    quote breaks the entire DOT source.

    中文:生成 DOT 用的双引号字符串。内嵌的双引号会被转义 —— 目录里的
    课程名合法地可能包含双引号,一个没转义的引号就会破坏整个 DOT 源码。
    """
    return '"' + str(label).replace('"', '\\"') + '"'


def _node_label(entry: dict) -> str:
    """Display label for a prereq/dependent entry: primary_code when the
    course resolved from the catalog, raw course_id for dangling seed
    edges (same fallback the prereq rows in the detail panel use).

    中文:先修课/后续课条目的显示标签:课程在目录里能解析到时用
    primary_code,悬空的种子边则用原始 course_id(与详情面板里先修课行
    使用的回退逻辑一致)。
    """
    return str(entry.get("primary_code") or entry["course_id"])


def build_prereq_dot(
    course_code: str,
    prereqs: list[dict],
    dependents: list[dict] | None = None,
) -> str:
    """DOT digraph for one course's prerequisite neighborhood.

    `prereqs` entries follow the /course/{id} `prerequisites` shape:
    {course_id, primary_code|None, requirement}. `dependents` (courses
    that require THIS one) may be None/empty — the API doesn't expose
    reverse edges yet; the parameter exists so the graph can grow
    without a signature change.

    Returns "" when there is nothing to draw, so callers skip the chart
    entirely instead of rendering a lonely single node.

    中文:某门课先修/后续邻域的 DOT 有向图。
    `prereqs` 条目遵循 /course/{id} 的 `prerequisites` 形状:
    {course_id, primary_code|None, requirement}。`dependents`(要求
    THIS 门课作为先修的课程)可以是 None/空 —— API 目前还不暴露反向边;
    保留这个参数是为了图未来能扩展、而不用改函数签名。
    没有东西可画时返回 "",这样调用方可以整个跳过图表,而不是画一个
    孤零零的单节点。
    """
    dependents = dependents or []
    if not prereqs and not dependents:
        return ""

    center = _q(course_code)
    # Build the DOT source line-by-line: header/graph-level attrs first,
    # then the center node, then prereq nodes + edges, then dependent
    # nodes + edges, closing brace last. Joined with "\n" at the end.
    # 中文:逐行构建 DOT 源码:先是头部/图级别属性,然后是中心节点,接着
    # 是先修课节点 + 边,再是后续课节点 + 边,最后收尾的花括号。末尾用
    # "\n" 拼接成完整字符串。
    lines: list[str] = [
        "digraph prereqs {",
        "  rankdir=TB;",
        '  bgcolor="transparent";',
        '  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=11];',
        '  edge [fontname="Helvetica", fontsize=9, color="#8A94A6"];',
        f'  {center} [fillcolor="{ALIPAY_BLUE}", fontcolor="#FFFFFF"];',
    ]

    prereq_nodes: list[str] = []
    edge_lines: list[str] = []
    for p in prereqs:
        node = _q(_node_label(p))
        prereq_nodes.append(node)
        requirement = str(p.get("requirement", ""))
        style = _EDGE_STYLE.get(requirement, "solid")
        # Edge points prereq -> center (arrow flows INTO the course); the
        # requirement tier both styles the line and labels it (raw value).
        # 中文:边的方向是 先修课 -> 中心课程(箭头流入本课程);
        # requirement 等级既决定线型,也直接作为标签文字(用原始值)。
        edge_lines.append(
            f"  {node} -> {center} [label={_q(requirement)}, style={style}];"
        )

    for node in prereq_nodes:
        lines.append(f'  {node} [fillcolor="#E8F1FF", fontcolor="#0C447C"];')
    if prereq_nodes:
        # rank=min pins all prereqs on the top row so the eye reads
        # prereqs → course → dependents straight down.
        # 中文:rank=min 把所有先修课钉在最上面一排,让视线能直接从
        # 先修课 → 本课程 → 后续课这样从上到下读下来。
        lines.append("  { rank=min; " + "; ".join(prereq_nodes) + "; }")
    lines.extend(edge_lines)

    for d in dependents:
        node = _q(_node_label(d))
        lines.append(f'  {node} [fillcolor="#F2F3F5", fontcolor="#646A73"];')
        lines.append(f"  {center} -> {node};")

    lines.append("}")
    return "\n".join(lines)


__all__ = ["build_prereq_dot"]
