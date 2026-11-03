"""Review regressions: real logging/resolution, conservative meaning, bounded UI work."""

import json
import logging
import os
import subprocess
import sys

import httpx
import pytest
import structlog

from schemas.plan_draft import DraftCourse, evaluate_draft
from schemas.program_plan import ProgramPlan
from tests.test_plan_draft import course, node
from tests.program_plan_support import plans
from tests.test_safe_error_exits import _json_logs


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


def test_nit_safe_catalog_year_diagnostic_is_preserved_but_arbitrary_text_is_not(monkeypatch):
    with _json_logs(monkeypatch) as stream, structlog.contextvars.bound_contextvars(path="/course/{course_id}"):
        logger = structlog.get_logger("synthetic.year")
        logger.warning("synthetic.valid", catalog_year="2026-2027")
        logger.warning("synthetic.invalid", catalog_year="PRIVATE_COURSE_TEXT")
        rows = [json.loads(line) for line in stream.getvalue().splitlines() if line.startswith("{")]
        assert next(r for r in rows if r["event"] == "synthetic.valid")["catalog_year"] == "2026-2027"
        assert "catalog_year" not in next(r for r in rows if r["event"] == "synthetic.invalid")
        assert "PRIVATE_COURSE_TEXT" not in stream.getvalue()
