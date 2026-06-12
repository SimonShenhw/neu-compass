"""Graphviz DOT builder for the course-prerequisite mini-graph.

The course-detail panel lists prereqs as flat rows; a two-level graph
reads faster once a course has 3+ edges ("what feeds into this, what does
it unlock"). st.graphviz_chart consumes a DOT source string directly, so
this stays a PURE string builder — no graphviz import, no Streamlit
import — testable with plain assertions like the ui_theme builders.

Visual language mirrors the Alipay theme (app/ui_theme.py): center course
solid #1677FF with white text, prereqs light blue #E8F1FF, dependents
neutral gray. Edge style encodes the requirement tier — required=solid,
recommended=dashed, concurrent=dotted — the same vocabulary as
schemas.program.PrereqRequirement, with the raw value as the edge label.

Layout: rankdir=TB with every prereq node pinned in a rank=min subgraph,
so prereqs sit on top and arrows flow DOWN into the course, then down
again to dependents. That matches how students read the relationship
("take A, then B") — rankdir=BT draws the same shape but flips the
arrow-reading order.
"""

from __future__ import annotations

ALIPAY_BLUE = "#1677FF"

# requirement → DOT edge style. Unknown values degrade to solid (drawn,
# just unstyled) rather than crashing the chart on a future tier.
_EDGE_STYLE: dict[str, str] = {
    "required": "solid",
    "recommended": "dashed",
    "concurrent": "dotted",
}


def _q(label: str) -> str:
    """DOT double-quoted string. Embedded double quotes get escaped —
    catalog course names can legally contain them, and one unescaped
    quote breaks the entire DOT source."""
    return '"' + str(label).replace('"', '\\"') + '"'


def _node_label(entry: dict) -> str:
    """Display label for a prereq/dependent entry: primary_code when the
    course resolved from the catalog, raw course_id for dangling seed
    edges (same fallback the prereq rows in the detail panel use)."""
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
    """
    dependents = dependents or []
    if not prereqs and not dependents:
        return ""

    center = _q(course_code)
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
        edge_lines.append(
            f"  {node} -> {center} [label={_q(requirement)}, style={style}];"
        )

    for node in prereq_nodes:
        lines.append(f'  {node} [fillcolor="#E8F1FF", fontcolor="#0C447C"];')
    if prereq_nodes:
        # rank=min pins all prereqs on the top row so the eye reads
        # prereqs → course → dependents straight down.
        lines.append("  { rank=min; " + "; ".join(prereq_nodes) + "; }")
    lines.extend(edge_lines)

    for d in dependents:
        node = _q(_node_label(d))
        lines.append(f'  {node} [fillcolor="#F2F3F5", fontcolor="#646A73"];')
        lines.append(f"  {center} -> {node};")

    lines.append("}")
    return "\n".join(lines)


__all__ = ["build_prereq_dot"]
