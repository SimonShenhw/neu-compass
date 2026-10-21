"""Review regressions: real logging/resolution, conservative meaning, bounded UI work."""

import contextlib
import json
import logging
import os
import subprocess
import sys

import httpx
import pytest
import structlog
from fastapi.testclient import TestClient

import app.api_client as clients
from app.api_client import ApiClient
from app.state_manager import add_draft_courses
from schemas.plan_draft import DraftCourse, DraftNode, evaluate_draft
from schemas.program_plan import ProgramPlan
from tests import test_plan_draft_view as draft_view_tests
from tests.conftest import build_test_app
from tests.page_layout_support import run
from tests.plan_draft_support import seed_documents, synthetic_courses
from tests.test_plan_draft import course, node
from tests.test_plan_draft_view import add, page, shown
from tests.test_program_plan_links import plans
from tests.test_safe_error_exits import _json_logs

backend = draft_view_tests.backend


@pytest.fixture(autouse=True)
def no_external_http(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Real external HTTP forbidden; only mock/ASGI or child Unix socket")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)


def actual(rule, courses=(), coverage="partial"):
    plan = ProgramPlan.model_validate({**plans()[0].model_dump(), "coverage": coverage, "requirements": rule.model_dump()})
    return evaluate_draft(plan, [DraftCourse(**c) for c in courses])


def test_h1_real_uvicorn_default_access_handler_does_not_record_course_reads():
    script = r'''
import io, logging, tempfile, threading, time
import httpx, uvicorn
from api.logging import configure_logging

async def app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"synthetic"})

with tempfile.TemporaryDirectory(prefix="i-access-") as directory:
    path = directory + "/a.sock"
    config = uvicorn.Config(app, uds=path, log_level="info", lifespan="off")
    configure_logging()
    configure_logging()
    logger = logging.getLogger("uvicorn.access")
    assert logger.propagate is False and logger.handlers
    output = io.StringIO()
    tap = logging.StreamHandler(output)
    tap.setFormatter(logger.handlers[0].formatter)
    logger.addHandler(tap)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        limit = time.monotonic() + 5
        while not server.started and time.monotonic() < limit:
            time.sleep(0.01)
        assert server.started
        with httpx.Client(transport=httpx.HTTPTransport(uds=path), base_url="http://synthetic", timeout=5) as client:
            for request in ["/resolve/course?ref=CS+5800", "/course/private-course-id?source=PRIVATE_QUERY",
                            "/course/private-course-id/requisites?year=PRIVATE_QUERY",
                            "/course/private-course-id/extra?ref=PRIVATE_QUERY", "/health?probe=retained"]:
                assert client.get(request).status_code == 200
    finally:
        server.should_exit = True
        thread.join(5)
        logger.removeHandler(tap)
    assert not thread.is_alive()
    text = output.getvalue()
    assert all(value not in text for value in ["CS+5800", "ref=", "private-course-id", "PRIVATE_QUERY"]), text
    assert 'GET /resolve/course HTTP/1.1' in text
    assert 'GET /course/{course_id} HTTP/1.1' in text
    assert 'GET /course/{course_id}/requisites HTTP/1.1' in text
    assert 'GET /health?probe=retained HTTP/1.1' in text
    assert text.count('200') == 5
print("default uvicorn handler: five real Unix-socket access records verified")
'''
    result = subprocess.run([sys.executable, "-B", "-c", script], capture_output=True, text=True,
                            env={**os.environ, "GEMINI_API_KEY": "ci-placeholder-not-a-secret", "PYTHONDONTWRITEBYTECODE": "1"}, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr


def test_h1_access_filter_is_reinstalled_idempotently_even_after_initial_setup(monkeypatch):
    from api.logging import configure_logging

    configure_logging()
    logger = logging.getLogger("uvicorn.access")
    monkeypatch.setattr(logger, "filters", [])
    configure_logging()
    configure_logging()
    assert len(logger.filters) == 1
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 0, '%s - "%s %s HTTP/%s" %d',
                               ("synthetic", "GET", "/course/private-id?ref=PRIVATE", "1.1", 200), None)
    assert logger.filter(record)
    assert record.args == ("synthetic", "GET", "/course/{course_id}", "1.1", 200)


@pytest.mark.parametrize("typed", ["CS 7140", "EECE 7397"])
def test_h2_crosslisting_uses_unique_exact_primary_from_real_resolver(empty_db, monkeypatch, typed):
    from db.alias_repository import AliasRepository
    from db.repository import CourseRepository
    from schemas.alias import Alias, AliasReviewStatus, AliasSource, AliasType
    from schemas.course import Course

    repo = CourseRepository(empty_db)
    pairs = [("synthetic-cs-7140", "CS 7140"), ("synthetic-eece-7397", "EECE 7397")]
    for cid, code in pairs:
        repo.insert(Course(course_id=cid, primary_code=code, primary_name="Synthetic " + code, credits=4), raw_text="synthetic")
        repo.mark_indexed(cid)
    for text, target in [("CS 7140", pairs[1][0]), ("EECE 7397", pairs[0][0])]:
        AliasRepository(empty_db).add(Alias(alias_text=text, alias_type=AliasType.CROSS_LISTED,
            primary_course_id=target, confidence=1.0, source=AliasSource.OFFICIAL, review_status=AliasReviewStatus.APPROVED))
    calls = []
    with TestClient(build_test_app(empty_db, seed=False)) as api:
        body = api.get("/resolve/course", params={"ref": typed}).json()
        assert len(body["matches"]) == 2 and sum(m["primary_code"] == typed for m in body["matches"]) == 1
        def forward(request):
            calls.append(request.url.path)
            response = api.get(request.url.path, params=dict(request.url.params))
            return httpx.Response(response.status_code, json=response.json())
        monkeypatch.setattr(clients, "ApiClient", lambda **kw: ApiClient(base_url="http://synthetic", transport=httpx.MockTransport(forward), **kw))
        app = page()
        add(app, typed)
        assert [c["code"] for c in app.session_state["plan_draft_courses"]] == [typed]
        assert len(calls) == 2 and calls[0] == "/resolve/course"
        assert "交叉列" in shown(app) and "向项目核实" in shown(app)


@pytest.mark.parametrize("duplicate_exact", [False, True])
def test_h2_checks_all_candidates_not_only_first_ten(backend, monkeypatch, duplicate_exact):
    matches = [{"course_id": f"other-{i}", "primary_code": f"DS {5000+i}", "primary_name": "Synthetic"} for i in range(11)]
    exact = {"course_id": "CS-5001", "primary_code": "CS 5001", "primary_name": "Synthetic"}
    matches += [exact, *([{**exact, "course_id": "second-exact"}] if duplicate_exact else [])]
    calls = []
    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"matches": matches} if request.url.path == "/resolve/course" else
                              {"course_id": "CS-5001", "primary_code": "CS 5001", "primary_name": "Synthetic", "credits": 4})
    monkeypatch.setattr(clients, "ApiClient", lambda **kw: ApiClient(base_url="http://synthetic", transport=httpx.MockTransport(handler), **kw))
    app = page()
    add(app, "CS5001")
    assert len(app.session_state["plan_draft_courses"]) == (0 if duplicate_exact else 1)
    assert len(calls) == (1 if duplicate_exact else 2)


def test_m1_parent_missing_keeps_select_and_or_groups_and_deduplicates():
    breadth = node("select", label="广度", course_codes=["CS 5100", "CS 5150", "CS 5500"], min_courses=2)
    exit_group = node("any_of", label="毕业出口", children=[
        node("select", label="Project", course_codes=["INFO 7945", "INFO 7990"], min_courses=1),
        node("all_of", label="Thesis", children=[node("course", course_code="INFO 7945"), node("course", course_code="INFO 7999")])])
    result = actual(node("all_of", children=[node("course", course_code="CS 5999"), breadth, exit_group]))
    text = "、".join(result.root.missing)
    assert "CS 5999" in text and "广度" in text and "2 门" in text and "毕业出口" in text
    assert not any(code in text for code in ["CS 5100", "CS 5150", "INFO 7945", "INFO 7990"])
    assert len(result.root.missing) == len(set(result.root.missing)) == 3
    assert result.summary_counts == {"met": 0, "missing": 2, "unknown": 0}


def test_m1_satisfied_exit_does_not_count_its_unused_alternative_as_missing():
    exits = node("any_of", label="exit", children=[node("select", label="Project", course_codes=["CS 5001"], min_courses=1),
        node("all_of", label="Thesis", children=[node("course", course_code="CS 5002"), node("course", course_code="CS 5003")])])
    result = actual(node("all_of", children=[exits, node("condition", label="Policy")]), [course()])
    assert result.summary_counts == {"met": 1, "missing": 0, "unknown": 0}
    assert result.root.children[0].missing == []


def test_m1_repeated_missing_course_is_listed_once():
    leaf = node("course", course_code="CS 5001")
    result = actual(node("all_of", children=[leaf, leaf]))
    assert result.root.missing == ["CS 5001"] and result.root.missing_omitted == 0


def test_m1_or_node_keeps_alternative_branch_labels_not_leaf_codes():
    first = node("all_of", label="Project", children=[node("course", course_code="INFO 7945"), node("condition", label="approval")])
    second = node("all_of", label="Thesis", children=[node("course", course_code="INFO 7945"), node("course", course_code="INFO 7990")])
    result = actual(node("any_of", label="Exit", children=[first, second])).root
    assert len(result.missing) == 2 and "Project" in result.missing[0] and "Thesis" in result.missing[1]
    assert all("INFO" not in item for item in result.missing) and result.missing_omitted == 0


def test_m1_parent_group_credit_gap_is_known_target_difference():
    pool = node("select", label="Electives", course_codes=["CS 5001", "CS 5002"], min_credits=8)
    result = actual(node("all_of", children=[pool, node("condition", label="Policy")]))
    assert result.root.missing == ["Electives（按已知确定学分距目标差 8 学分）"]


def test_m2_excluded_courses_are_mentioned_even_when_they_cannot_count():
    pool = node("select", subject_codes=["CS"], excluded_course_codes=["CS 5001"], min_courses=1)
    result = actual(pool, [course(), course("DS 5001")])
    assert result.unplaced == ["DS 5001"]
    assert any("CS 5001" in reason and "明确排除" in reason for reason in result.root.reasons)


def test_l1_unknown_course_count_never_says_zero_courses_missing():
    result = actual(node("select", subject_codes=["CS"], min_courses=1), [course()])
    assert result.root.status == "unknown" and result.root.shortfall["courses"] == 0
    assert not any("还差 0 门" in reason for reason in result.root.reasons)
    assert any("确定计入 0 门" in reason for reason in result.root.reasons)


def test_l2_empty_batch_is_none_not_duplicate():
    state = {"plan_draft_courses": []}
    old = state["plan_draft_courses"]
    assert add_draft_courses(state, []) == "none" and state["plan_draft_courses"] is old


@pytest.mark.parametrize("raw", ["<b>bad</b>", "CS5001"])
def test_l2_nit_no_success_keeps_input_and_has_no_duplicate_notice(backend, raw):
    backend["missing"].add("CS 5001")
    app = page()
    add(app, raw)
    assert not app.session_state["plan_draft_courses"]
    assert "重复" not in " ".join(e.value for e in app.info)
    assert app.text_area(key="plan-draft-input").value == raw


def test_l3_capacity_preflight_does_not_send_requests_and_names_correct_excess(backend):
    app = page()
    old = [course(f"CS {5100+i}") for i in range(19)]
    app.session_state["plan_draft_courses"] = old
    add(app, "CS6000 CS6001 CS6002")
    assert app.session_state["plan_draft_courses"] == old and backend["calls"] == []
    assert "2 门" in shown(app) and "未核对" in shown(app)


@pytest.mark.parametrize("fail_detail", [False, True])
def test_l4_transport_failure_stops_batch_with_remaining_count(backend, monkeypatch, fail_detail):
    calls = []
    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/resolve/course" and fail_detail:
            return httpx.Response(200, json={"matches": [{"course_id": "CS-5000", "primary_code": "CS 5000", "primary_name": "Synthetic"}]})
        raise httpx.ConnectError("synthetic PRIVATE exception", request=request)
    monkeypatch.setattr(clients, "ApiClient", lambda **kw: ApiClient(base_url="http://synthetic", transport=httpx.MockTransport(handler), **kw))
    app = page()
    add(app, " ".join(f"CS{5000+i}" for i in range(20)))
    assert len(calls) == (2 if fail_detail else 1) and not app.session_state["plan_draft_courses"]
    assert "后面 19 门未核对" in shown(app) and "PRIVATE" not in shown(app)


def test_l4_spinner_surrounds_requests_and_keeps_prior_success_on_failure(backend, monkeypatch):
    import streamlit as st

    active = []
    observed = []
    original_spinner = st.spinner
    @contextlib.contextmanager
    def spinner(*args, **kwargs):
        with original_spinner(*args, **kwargs):
            active.append(True)
            try:
                yield
            finally:
                active.pop()
    monkeypatch.setattr(st, "spinner", spinner)
    def handler(request):
        observed.append(bool(active))
        if request.url.params.get("ref") == "CS 5002":
            raise httpx.ReadTimeout("synthetic", request=request)
        return httpx.Response(200, json={"matches": [{"course_id": "CS-5001", "primary_code": "CS 5001", "primary_name": "Synthetic"}]} if request.url.path == "/resolve/course" else
            {"course_id": "CS-5001", "primary_code": "CS 5001", "primary_name": "Synthetic", "credits": 4})
    monkeypatch.setattr(clients, "ApiClient", lambda **kw: ApiClient(base_url="http://synthetic", transport=httpx.MockTransport(handler), **kw))
    app = page()
    add(app, "CS5001 CS5002 CS5003")
    assert observed == [True, True, True] and active == []
    assert [c["code"] for c in app.session_state["plan_draft_courses"]] == ["CS 5001"]
    assert "后面 1 门未核对" in shown(app)


def test_l5_each_control_and_link_names_its_course(backend):
    app = page()
    add(app, "CS5001 CS5002")
    for code in ["CS 5001", "CS 5002"]:
        assert code in app.button(key="draft-remove-" + code).label
        assert any(f"[{code}" in m.value and "课程页" in m.value for m in app.markdown)


def test_l6_share_separator_spellings_normalize_before_resolving(backend):
    app = page()
    add(app, "CS-5001 cs_5002 CS 5001")
    assert [c["code"] for c in app.session_state["plan_draft_courses"]] == ["CS 5001", "CS 5002"]
    assert len(backend["calls"]) == 4


@pytest.mark.parametrize("kind", ["course", "all_of", "select"])
def test_l7_complete_plan_root_is_never_met_but_children_keep_status(kind):
    leaf = node("course", course_code="CS 5001")
    rule = leaf if kind == "course" else node("all_of", children=[leaf, node("course", course_code="CS 5002")]) if kind == "all_of" else node("select", course_codes=["CS 5001"], min_courses=1)
    result = actual(rule, [course(), course("CS 5002")], coverage="complete")
    assert result.root.status == "unknown" and result.root.reasons
    assert all(child.status == "met" for child in result.root.children)


def test_nit_root_disclaimer_counts_displaced_reasons():
    excluded = [f"CS {5000+i}" for i in range(19)]
    rule = node("select", course_codes=[*excluded, "CS 5999"], excluded_course_codes=excluded, min_courses=1)
    result = actual(rule, [course(code) for code in [*excluded, "CS 5999"]], coverage="complete")
    assert result.root.status == "unknown" and len(result.root.reasons) == 10 and result.root.reasons_omitted == 10


def test_nit_render_does_not_duplicate_unknown_credits_or_add_empty_operator_space():
    from app.plan_draft_view import _tree_lines

    leaf = DraftNode(kind="course", label="Synthetic", status="met")
    assert "—  " not in _tree_lines(leaf)[0]
    selection = DraftNode(kind="select", label="Synthetic", status="unknown", counted=["CS 5001", "CS 5002"], possible=["CS 5002"])
    lines = _tree_lines(selection)
    counted = next(line for line in lines if "按填写计入" in line)
    possible = next(line for line in lines if "学分未知" in line)
    assert "CS 5001" in counted and "CS 5002" not in counted and "CS 5002" in possible


def test_nit_safe_catalog_year_diagnostic_is_preserved_but_arbitrary_text_is_not(monkeypatch):
    with _json_logs(monkeypatch) as stream, structlog.contextvars.bound_contextvars(path="/course/{course_id}"):
        logger = structlog.get_logger("synthetic.year")
        logger.warning("synthetic.valid", catalog_year="2026-2027")
        logger.warning("synthetic.invalid", catalog_year="PRIVATE_COURSE_TEXT")
        rows = [json.loads(line) for line in stream.getvalue().splitlines() if line.startswith("{")]
        assert next(r for r in rows if r["event"] == "synthetic.valid")["catalog_year"] == "2026-2027"
        assert "catalog_year" not in next(r for r in rows if r["event"] == "synthetic.invalid")
        assert "PRIVATE_COURSE_TEXT" not in stream.getvalue()


@pytest.mark.parametrize("seed,plan", seed_documents(), ids=[f"{seed}:{p.plan_id}" for seed, p in seed_documents()])
def test_ten_seed_pages_keep_conservative_language_without_requests(backend, seed, plan):
    app = page(plan)
    app.session_state["plan_draft_courses"] = [c.model_dump() for c in synthetic_courses(plan)]
    run(app)
    text = shown(app)
    assert all(phrase not in text for phrase in ["全部满足", "满足全部", "满足所有", "可以毕业", "能毕业", "符合要求", "毕业资格"]), seed
    tree = next(e.value for e in app.text if plan.requirements.label in e.value)
    assert not tree.splitlines()[0].startswith("✅") and backend["calls"] == []
