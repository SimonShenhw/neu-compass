"""Tests for rag.prereq_graph — pure DOT string builder.

No graphviz runtime needed: st.graphviz_chart takes the DOT source as-is,
so correctness here is string-level (nodes present, edge styles encode
requirement tiers, catalog data can't break the quoting).
"""

from __future__ import annotations

from rag.prereq_graph import build_prereq_dot


def test_empty_inputs_return_empty_string() -> None:
    assert build_prereq_dot("CS 5800", []) == ""
    assert build_prereq_dot("CS 5800", [], dependents=[]) == ""
    assert build_prereq_dot("CS 5800", [], dependents=None) == ""


def test_center_node_filled_blue_with_prereqs_on_top_rank() -> None:
    dot = build_prereq_dot(
        "CS 5800",
        [{"course_id": "neu-cs5004", "primary_code": "CS 5004",
          "requirement": "required"}],
    )
    assert dot.startswith("digraph")
    assert '"CS 5800" [fillcolor="#1677FF", fontcolor="#FFFFFF"];' in dot
    assert '"CS 5004" -> "CS 5800"' in dot
    assert 'rank=min; "CS 5004";' in dot


def test_requirement_tiers_map_to_edge_styles() -> None:
    dot = build_prereq_dot(
        "AAI 6600",
        [
            {"course_id": "a", "primary_code": "CS 5100", "requirement": "required"},
            {"course_id": "b", "primary_code": "DS 5220", "requirement": "recommended"},
            {"course_id": "c", "primary_code": "CS 5800", "requirement": "concurrent"},
        ],
    )
    assert 'label="required", style=solid' in dot
    assert 'label="recommended", style=dashed' in dot
    assert 'label="concurrent", style=dotted' in dot


def test_missing_primary_code_falls_back_to_course_id() -> None:
    dot = build_prereq_dot(
        "CS 5800",
        [{"course_id": "neu-unknown", "primary_code": None,
          "requirement": "required"}],
    )
    assert '"neu-unknown"' in dot


def test_double_quotes_in_labels_are_escaped() -> None:
    dot = build_prereq_dot(
        'CS "Algo" 5800',
        [{"course_id": "x", "primary_code": 'Pre "Req"',
          "requirement": "required"}],
    )
    assert '\\"Algo\\"' in dot
    assert '\\"Req\\"' in dot
    assert '"CS "' not in dot


def test_dependents_draw_gray_with_edges_from_center() -> None:
    dot = build_prereq_dot(
        "CS 5800",
        [],
        dependents=[{"course_id": "neu-cs7800", "primary_code": "CS 7800"}],
    )
    assert '"CS 5800" -> "CS 7800";' in dot
    assert '"CS 7800" [fillcolor="#F2F3F5", fontcolor="#646A73"];' in dot
