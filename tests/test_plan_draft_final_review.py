"""Round-21 review fixes (A22, B22): the range line once, list separators and full-width input, a match under
another code, log value shapes, exact course links, and the tests the reviewers' surviving mutants showed missing.
中文：第 21 轮评审的修复和补测；每条测试注明对应的评审编号。
"""

import json
import re
from pathlib import Path

import httpx
import pytest
import structlog
from markdown_it import MarkdownIt

from app.plan_draft_view import _tree_lines, parse_course_codes
from schemas.plan_draft import DraftNode
from tests import test_plan_draft_view as draft_view_tests
from tests.test_plan_draft import course, evaluate_rule, node
from tests.test_plan_draft_view import add, page, shown
from tests.test_program_plan_links import plans
from tests.test_safe_error_exits import _json_logs

backend = draft_view_tests.backend
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def no_external_http(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Real external HTTP forbidden; only mock transports")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)


def rows(stream):
    return {row["event"]: row for row in (json.loads(line) for line in stream.getvalue().splitlines() if line.startswith("{"))}


def test_a22_la_range_line_appears_once_when_count_and_credit_targets_are_both_unmet():
    result = evaluate_rule(node("select", subject_codes=["CS"], min_courses=2, min_credits=8), [course("CS 5999")])
    assert result.status == "missing"
    assert [r for r in result.reasons if r.startswith("范围内可能计入")] == ["范围内可能计入：CS 5999；是否能算，要项目确认。"]
    assert result.reasons[1].startswith("范围内可能计入")  # Still right after the first unmet target.


@pytest.mark.parametrize("raw,codes,invalid", [
    ("CS 5010、CS 5800", ["CS 5010", "CS 5800"], []),
    ("CS5010/CS5800", ["CS 5010", "CS 5800"], []),
    ("CS 5010，CS 5800；DS 5001", ["CS 5010", "CS 5800", "DS 5001"], []),
    ("ＣＳ　５０１０", ["CS 5010"], []),
    ("CS ５０１０", ["CS 5010"], []),
    ("CS-5010 cs_5800", ["CS 5010", "CS 5800"], []),
    ("neu-cs-6130", [], ["neu-cs-6130"]),
])
def test_a22_lb_list_separators_full_width_input_and_internal_ids(raw, codes, invalid):
    assert parse_course_codes(raw) == (codes, invalid)


def test_a22_lb_page_adds_codes_separated_by_the_chinese_list_comma(backend):
    app = page()
    add(app, "CS5001、CS5002")
    assert [c["code"] for c in app.session_state["plan_draft_courses"]] == ["CS 5001", "CS 5002"]
    assert "格式不正确" not in shown(app)


@pytest.mark.parametrize("raw", ["[x](https:elsewhere.example)", "<https:elsewhere.example>"])
def test_a22_lb_a_link_that_stays_one_token_is_escaped_in_the_format_warning(backend, raw):
    # "/" now splits "[x](https://elsewhere.example)" before the warning, so these inputs stay one token.
    assert parse_course_codes(raw) == ([], [raw])
    app = page()
    add(app, raw)
    assert not backend["calls"] and not app.session_state["plan_draft_courses"]
    rendered = "\n".join(MarkdownIt("commonmark").render(e.value) for e in app.warning)
    assert "课号格式不正确" in rendered and "<a href=" not in rendered


def test_a22_lc_a_single_match_under_another_code_is_named(backend):
    backend["crosslisted"]["EECE 7397"] = "CS 7140"
    app = page()
    add(app, "EECE7397 CS5001")
    assert [c["code"] for c in app.session_state["plan_draft_courses"]] == ["CS 7140", "CS 5001"]
    [notice] = [e.value for e in app.warning if "对应主课号" in e.value]
    assert "EECE 7397" in notice and "CS 7140" in notice and "请向项目核实" in notice


@pytest.mark.parametrize("kind", ["all_of", "any_of"])
def test_a22_ld_a09_a_group_of_only_optional_branches_below_the_root_is_not_met(kind):
    optional = node("optional", activate_when="Thesis approval", children=[node("course", course_code="CS 5001")])
    result = evaluate_rule(node(kind, children=[optional, optional]), [course()])
    assert result.status == "unknown" and "只有可选分支" in " ".join(result.reasons)


def test_a22_ld_a08_an_excluded_code_is_never_listed_as_missing():
    rule = node("select", course_codes=["CS 5001", "CS 5002"], excluded_course_codes=["CS 5001"], min_courses=1)
    result = evaluate_rule(rule)
    assert result.status == "missing" and result.missing == ["CS 5002"]


def test_a22_ld_a11_an_or_parent_names_the_code_of_a_missing_course_exit():
    rule = node("any_of", children=[node("course", label="Algorithms", course_code="CS 5800"),
                                    node("course", label="Networks", course_code="CS 5700")])
    assert evaluate_rule(rule).missing == ["Algorithms（CS 5800）", "Networks（CS 5700）"]


def test_a22_ld_a07_a_reuse_reason_names_only_groups_that_apply_at_the_same_time():
    group_b = node("select", label="Group B", course_codes=["CS 5001"], min_courses=1)
    group_a = node("select", label="Group A", course_codes=["CS 5001"], min_courses=1)
    exit_c = node("select", label="Exit C", course_codes=["CS 5001"], min_courses=1)
    result = evaluate_rule(node("any_of", children=[node("all_of", children=[group_b, group_a]), exit_c]), [course()])
    [reason] = [r for r in result.children[0].children[0].reasons if "重复计入" in r]
    assert "Group A" in reason and "Exit C" not in reason


def test_a22_ld_a14_a15_omitted_candidates_and_reasons_are_announced():
    lines = _tree_lines(DraftNode(kind="select", label="Synthetic", status="missing", missing=["CS 5001"],
                                  missing_omitted=2, reasons=["Synthetic reason"], reasons_omitted=3))
    assert "  另有 2 项候选／子项未展开。" in lines and "  另有 3 项原因未展开。" in lines


def test_a22_ld_a17_a18_partial_plan_and_unplaced_course_captions(backend):
    plan = plans()[0].model_copy(update={"coverage": "partial", "requirements": node("course", course_code="CS 5001")})
    app = page(plan)
    add(app, "CS5999")
    captions = [e.value for e in app.caption]
    assert "这个方案只记录了部分规则；上述统计不是个人学位或注册审核。" in captions
    assert "方案里没有写到这门课；不代表不能算，也不代表能算，请向项目核实。" in captions


def test_a22_ld_a22_invalid_token_warnings_are_capped_at_ten(backend):
    app = page()
    add(app, " ".join(f"bad{i}" for i in range(12)))
    assert len([e for e in app.warning if "课号格式不正确" in e.value]) == 10
    assert any("另有 2 项格式不正确" in e.value for e in app.warning) and not backend["calls"]


def test_b22_low1_the_api_is_started_at_the_root_path():
    """Course-read redaction matches request paths as the app sees them; see docs/pii_redaction.md section 10.
    uvicorn reads the same setting from UVICORN_ROOT_PATH; the NAS `.env` is outside the repository."""
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    [command] = [line for line in dockerfile.splitlines() if line.startswith("CMD")]
    assert "uvicorn" in command
    for text in [dockerfile, (ROOT / "docker-compose.yml").read_text(encoding="utf-8")]:
        assert re.search(r"root[-_]path", text, re.IGNORECASE) is None


def test_b22_low2a_course_read_lines_keep_the_template_even_with_an_explicit_path(monkeypatch):
    with _json_logs(monkeypatch) as stream, structlog.contextvars.bound_contextvars(path="/course/{course_id}"):
        structlog.get_logger("synthetic.paths").warning("synthetic.explicit_path", path="/course/private-raw-id")
    assert rows(stream)["synthetic.explicit_path"]["path"] == "/course/{course_id}"
    assert "private-raw-id" not in stream.getvalue()


def test_b22_low2b_course_read_lines_drop_allowed_keys_whose_values_are_not_the_logged_shape(monkeypatch):
    frame = "course_requisite_repository.py:120 list_for_course"
    with _json_logs(monkeypatch) as stream, structlog.contextvars.bound_contextvars(path="/course/{course_id}"):
        logger = structlog.get_logger("synthetic.values")
        logger.warning("synthetic.wrong_shapes", courses=["private-id-1", "private-id-2"], count=2, dangling=True,
                       error_type="private id text", exc_type="OperationalError", frames=["private-id-3"])
        logger.warning("synthetic.logged_shapes", courses=3, frames=[frame], error_type="internal_error", duration_ms=1.5)
    events = rows(stream)
    wrong, logged = events["synthetic.wrong_shapes"], events["synthetic.logged_shapes"]
    assert "private-id" not in stream.getvalue() and "private id text" not in stream.getvalue()
    assert not {"courses", "dangling", "error_type", "frames"} & wrong.keys()
    assert wrong["count"] == 2 and wrong["exc_type"] == "OperationalError"
    assert (logged["courses"], logged["frames"], logged["error_type"], logged["duration_ms"]) == (3, [frame], "internal_error", 1.5)


def test_b22_low3_each_draft_link_is_exactly_its_own_course_link(backend):
    from app.deep_links import course_share_ref, share_url
    from config import settings

    app = page()
    add(app, "CS5001 CS5002")
    links = [e.value for e in app.markdown if "课程页／年度先修" in e.value]
    assert links == [f"[{code} · 课程页／年度先修]({share_url(settings.public_base_url, course=course_share_ref(code))})"
                     for code in ["CS 5001", "CS 5002"]]


@pytest.fixture
def crosslisted(monkeypatch):
    """Two course records per cross-listed pair, each matching both refs, as ingest stores them (H2)."""
    import app.api_client as clients

    original, trace = clients.ApiClient, {"calls": [], "pairs": {"CS 7140": ["CS 7140", "EECE 7397"],
                                                               "EECE 7397": ["EECE 7397", "CS 7140"]}}

    def handler(request):
        trace["calls"].append(request.url.path)
        if request.url.path == "/resolve/course":
            ref = request.url.params["ref"]
            return httpx.Response(200, json={"ref": ref, "matches": [
                {"course_id": code.replace(" ", "-"), "primary_code": code, "primary_name": "Synthetic " + code}
                for code in trace["pairs"].get(ref, [ref])]})
        code = request.url.path.rsplit("/", 1)[1].replace("-", " ")
        return httpx.Response(200, json={"course_id": code.replace(" ", "-"), "primary_code": code,
                                        "primary_name": "Synthetic " + code, "credits": 4})

    monkeypatch.setattr(clients, "ApiClient", lambda **kwargs: original(
        base_url="http://synthetic-draft", transport=httpx.MockTransport(handler), **kwargs))
    return trace


def pair_plan():
    rule = node("all_of", label="root", children=[
        node("select", label="Two from list", course_codes=["CS 7140", "EECE 7397", "CS 6140"], min_courses=2),
        node("condition", label="GPA")])
    return plans()[0].model_copy(update={"requirements": rule})


def twin_notices(app):
    return [e.value for e in app.warning if "可能是同一门交叉列出的课" in e.value]


@pytest.mark.parametrize("raw,kept,skipped", [("CS 7140/EECE 7397", "CS 7140", "EECE 7397"),
                                              ("EECE 7397 CS 7140", "EECE 7397", "CS 7140")])
def test_recheck1_r1_a_cross_listed_pair_typed_together_counts_once(crosslisted, raw, kept, skipped):
    app = page(pair_plan())
    add(app, raw)
    assert [c["code"] for c in app.session_state["plan_draft_courses"]] == [kept]
    assert twin_notices(app) == [f"{skipped} 和 {kept} 可能是同一门交叉列出的课，只按 {kept} 计入；如果是两门不同的课，请向项目核实。"]
    assert crosslisted["calls"].count("/resolve/course") == 2 and len(crosslisted["calls"]) == 3  # No detail GET for the twin.
    [group] = [line.strip() for e in app.text for line in e.value.splitlines() if "组选（非全部必修） Two from list" in line]
    assert group.startswith("⬜ 还缺")


def test_recheck1_r1_the_twin_of_a_course_already_in_the_draft_is_not_added(crosslisted):
    app = page(pair_plan())
    add(app, "CS 7140")
    add(app, "EECE 7397")
    assert [c["code"] for c in app.session_state["plan_draft_courses"]] == ["CS 7140"]
    assert twin_notices(app) == ["EECE 7397 和 CS 7140 可能是同一门交叉列出的课，只按 CS 7140 计入；如果是两门不同的课，请向项目核实。"]


@pytest.mark.parametrize("listed_by", ["CS 7140", "EECE 7397"])
def test_recheck1_r1_a_pair_is_caught_when_only_one_record_names_the_other(crosslisted, listed_by):
    crosslisted["pairs"] = {listed_by: crosslisted["pairs"][listed_by]}
    app = page(pair_plan())
    add(app, "CS 7140 EECE 7397")
    assert [c["code"] for c in app.session_state["plan_draft_courses"]] == ["CS 7140"]
    assert len(twin_notices(app)) == 1


def test_recheck1_r1_unrelated_courses_and_a_single_exact_match_are_still_added(crosslisted):
    app = page(pair_plan())
    add(app, "CS 7140 CS 6140")
    assert [c["code"] for c in app.session_state["plan_draft_courses"]] == ["CS 7140", "CS 6140"]
    assert not twin_notices(app) and any("同一引用也匹配 EECE 7397" in e.value for e in app.warning)


def test_recheck1_r2_frames_from_frozen_stdlib_modules_are_kept_on_course_reads(monkeypatch):
    """error_frames() writes basename:line name; Python 3.12 runs os, posixpath and importlib frozen."""
    frames = ["course.py:41 get_course", "<frozen os>:685 __getitem__", "<frozen importlib._bootstrap_external>:995 exec_module"]
    with _json_logs(monkeypatch) as stream, structlog.contextvars.bound_contextvars(path="/course/{course_id}"):
        logger = structlog.get_logger("synthetic.frames")
        logger.error("synthetic.frozen_frames", exc_type="KeyError", frames=frames)
        logger.error("synthetic.spaced_frames", exc_type="KeyError", frames=["<frozen private id text>:1 read"])
    events = rows(stream)
    assert events["synthetic.frozen_frames"]["frames"] == frames
    assert "frames" not in events["synthetic.spaced_frames"] and "private id text" not in stream.getvalue()
