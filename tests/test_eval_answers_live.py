"""scripts/eval_answers_live.py offline: GET-only fetch with the eval tag, cases built like /chat,
and full runs with a fake model (no network, no Gemini).

中文：离线测试 scripts/eval_answers_live.py：只用带评测标记的 GET 取数据、按 /chat 的方式构造
用例、用假模型跑完整流程（不联网、不调 Gemini）。
"""

from __future__ import annotations

import json

import httpx
import pytest

from scripts.eval_answers_live import DEFAULT_QUESTIONS, build_case, fetch_courses, main, run

CATALOG = "https://catalog.northeastern.edu/course-descriptions/cs/"


def payload(course_id="neu-cs-5800", code="CS 5800", name="Algorithms", *, snapshot=True, quote="About 12 hours a week"):
    from db.catalog_source_repository import CatalogSourceRepository  # noqa: PLC0415
    from rag.answer_evidence import course_answer_evidence  # noqa: PLC0415
    from schemas.course import Course  # noqa: PLC0415
    from scrapers.neu_catalog import CatalogEntry  # noqa: PLC0415

    course = Course(course_id=course_id, primary_code=code, primary_name=name, workload_hours_per_week=12.0,
                    difficulty_score=4.0, prereqs=["CS 5002"], source_review_ids=["rmp_review_a"],
                    evidence_snippets=[{"field": "workload_hours_per_week", "value": 12, "source_id": "rmp_review_a",
                                        "quote": quote, "confidence": 0.8},
                                       {"field": "difficulty_score", "value": 4.0, "source_id": "rmp_review_a",
                                        "quote": "Very hard exams", "confidence": 0.7}])
    catalog = CatalogSourceRepository.snapshot(CatalogEntry(
        course_code=code, course_name=name, description="Graphs.", catalog_url=CATALOG)) if snapshot else None
    data = course.model_dump(mode="json")
    data["answer_evidence"] = course_answer_evidence(course, catalog).model_dump(mode="json")
    return data


PAYLOADS = {"neu-cs-5800": payload(), "neu-cs-5200": payload("neu-cs-5200", "CS 5200", "Databases", snapshot=False,
                                                             quote="Heavy weekly homework")}
QUESTION = {"qid": "Q1", "lang": "zh", "query": "CS 5800 和 CS 5200 哪门课更难？", "course_ids": ["neu-cs-5800", "neu-cs-5200"],
            "route": "alias", "notices": []}


def test_fetch_reads_each_course_once_with_get_and_the_eval_tag():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path, request.headers.get("X-Eval-Run")))
        return httpx.Response(200, json=PAYLOADS["neu-cs-5800"])

    with httpx.Client(base_url="http://api.test", headers={"X-Eval-Run": "tag"}, transport=httpx.MockTransport(handler)) as client:
        assert list(fetch_courses(client, ["neu-cs-5800", "neu-cs-5800"])) == ["neu-cs-5800"]
    assert seen == [("GET", "/course/neu-cs-5800", "tag")]
    with httpx.Client(base_url="http://api.test", transport=httpx.MockTransport(lambda r: httpx.Response(404))) as client:
        with pytest.raises(RuntimeError, match="returned 404"):
            fetch_courses(client, ["neu-x"])


def test_case_is_built_like_chat_and_the_context_reflects_the_evidence():
    prompt, context = build_case(QUESTION, PAYLOADS)
    assert "snapshot_id" not in prompt and "rmp_review_a" not in prompt  # The 4.x projection.
    assert context.allowed_urls == {CATALOG} and context.lang == "zh"
    assert context.no_catalog_relevant and context.fetch_date_relevant and context.prereq_relevant
    assert context.has_rmp_data and not context.program_notice
    # No quote states 4.0 (difficulty); 12 is stated for CS 5800 but not for CS 5200.
    assert context.unstated_values == (4.0, 12.0)
    _, only_5800 = build_case({**QUESTION, "course_ids": ["neu-cs-5800"]}, PAYLOADS)
    assert only_5800.unstated_values == (4.0,)  # Its quote states the 12 hours.
    assert not only_5800.no_catalog_relevant
    assert {"field_evidence", "recorded_sources", "primary_code"} <= context.prompt_keys


def test_dry_run_writes_prompts_and_makes_no_model_calls(tmp_path):
    report = run([QUESTION], PAYLOADS, out=tmp_path, runs=2, max_calls=5, stream_fn=None)
    assert report["model_calls"] == 0 and report["records"] == []
    assert report["status"] == "dry run" and report["planned_calls"] == 0
    saved = json.loads((tmp_path / "prompts" / "Q1.context.json").read_text(encoding="utf-8"))
    assert saved["lang"] == "zh" and saved["allowed_urls"] == [CATALOG]  # The context is kept as well.
    assert (tmp_path / "prompts" / "Q1.txt").read_text(encoding="utf-8").startswith("You are a concise")
    assert json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))["summary"]["answers"] == 0


def test_runs_check_every_answer_and_stop_at_the_call_cap(tmp_path):
    answers = iter([f"CS 5800 的内容来自 [NEU 官方课程目录]({CATALOG}) 的存档副本，不是实时核对。", "Leaked neu-cs-5800.",
                    "never reached"])
    calls = []

    def fake(prompt):
        calls.append(prompt)
        yield next(answers)

    report = run([QUESTION], PAYLOADS, out=tmp_path, runs=3, max_calls=2, stream_fn=fake)
    assert len(calls) == 2 and report["model_calls"] == 2 and len(report["records"]) == 2
    assert report["planned_calls"] == 3 and report["status"] == "incomplete"  # The cap stopped it early.
    assert report["summary"]["ids_fail"] == 1 and report["summary"]["links_fail"] == 0
    assert (tmp_path / "answers" / "Q1_run1.md").exists() and (tmp_path / "answers" / "Q1_run2.md").exists()
    assert "| Q1 run 2 | ids_fail |" in (tmp_path / "summary.md").read_text(encoding="utf-8")


def test_model_errors_are_recorded_with_the_key_redacted(tmp_path):
    def broken(prompt):
        raise RuntimeError("upstream rejected key SECRET-KEY-VALUE")
        yield  # pragma: no cover - makes this a generator, like the real stream

    report = run([QUESTION], PAYLOADS, out=tmp_path, runs=1, max_calls=1, stream_fn=broken, secret="SECRET-KEY-VALUE")
    assert report["errors"] == 1 and "checks" not in report["records"][0] and report["status"] == "incomplete"
    saved = (tmp_path / "results.json").read_text(encoding="utf-8")
    assert "SECRET-KEY-VALUE" not in saved and "[REDACTED]" in saved


def fake_api(monkeypatch):
    real_client = httpx.Client

    def handler(request):
        course_id = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json=payload(course_id, "CS " + course_id[-4:], "Course " + course_id[-4:]))

    monkeypatch.setattr(httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))


def fake_model(monkeypatch, answers):
    """generate_text_stream yields the next answer in turn; an exception in the list is raised."""
    import llm.gemini_client as gemini  # noqa: PLC0415
    from config import settings  # noqa: PLC0415

    script = iter(answers)

    def stream(prompt):
        answer = next(script)
        if isinstance(answer, Exception):
            raise answer
        yield answer

    monkeypatch.setattr(gemini, "generate_text_stream", stream)
    monkeypatch.setattr(settings, "gemini_api_key", "test-key-not-real")


PLAIN = "这门课讲图算法。"


@pytest.mark.parametrize("answers, code, status", [
    ([PLAIN] * 5, 0, "complete"),
    ([RuntimeError("upstream unavailable")] * 5, 3, "incomplete"),  # Nothing was checked.
    ([PLAIN] * 4 + [RuntimeError("timeout")], 3, "incomplete"),
    ([PLAIN] * 4 + ["Leaked neu-cs-5800."], 1, "complete"),
    (["Leaked neu-cs-5800."] + [RuntimeError("timeout")] * 4, 1, "incomplete"),  # A hard failure comes first.
])
def test_exit_code_tells_complete_incomplete_and_failed_runs_apart(answers, code, status, tmp_path, monkeypatch):
    fake_api(monkeypatch)
    fake_model(monkeypatch, answers)
    assert main(["--api-base", "http://api.test", "--out", str(tmp_path), "--runs", "1"]) == code
    report = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert report["status"] == status and report["planned_calls"] == report["model_calls"] == 5
    assert (tmp_path / "summary.md").read_text(encoding="utf-8").splitlines()[0].endswith(f"· {status}")


def test_a_run_stopped_by_the_call_cap_is_incomplete(tmp_path, monkeypatch):
    fake_api(monkeypatch)
    fake_model(monkeypatch, [PLAIN] * 3)
    assert main(["--api-base", "http://api.test", "--out", str(tmp_path), "--runs", "2", "--max-calls", "3"]) == 3
    report = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert (report["planned_calls"], report["model_calls"], report["status"]) == (10, 3, "incomplete")


@pytest.mark.parametrize("flag", ["--runs", "--max-calls"])
def test_runs_and_the_call_cap_must_be_positive(flag, tmp_path):
    with pytest.raises(SystemExit) as raised:
        main(["--api-base", "http://api.test", "--out", str(tmp_path), flag, "0"])
    assert raised.value.code == 2


def test_rescore_keeps_the_original_runs_errors(tmp_path):
    answers = iter([PLAIN, RuntimeError("timeout")])

    def stream(prompt):
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        yield answer

    run([QUESTION], PAYLOADS, out=tmp_path, runs=2, max_calls=5, stream_fn=stream)
    assert main(["--rescore", str(tmp_path / "results.json")]) == 3
    rescored = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert rescored["errors"] == 1 and rescored["status"] == "incomplete"


def test_status_of_reports_written_before_the_plan_was_recorded():
    from scripts.eval_answers_live import run_status  # noqa: PLC0415

    checked = {"checks": {}}
    assert run_status({"model_calls": 0, "records": [], "errors": 0}) == "dry run"
    assert run_status({"model_calls": 2, "records": [checked, checked], "errors": 0}) == "complete"
    assert run_status({"model_calls": 2, "records": [checked, {"error": "x"}], "errors": 1}) == "incomplete"
    # A real run that planned nothing checked nothing: never "complete".
    assert run_status({"dry_run": False, "planned_calls": 0, "model_calls": 0, "records": [], "errors": 0}) == (
        "incomplete")


@pytest.mark.parametrize("questions_text", [
    "not json", "[]", '[{"qid": "Q1"}]', json.dumps([{**QUESTION, "course_ids": []}]),
    json.dumps([{**QUESTION, "route": "guess"}]), json.dumps([{**QUESTION, "lang": "fr"}]),
    json.dumps([{**QUESTION, "notices": "program_schedule_unverified"}]),
    json.dumps([{**QUESTION, "course_ids": [5800]}]), json.dumps([{**QUESTION, "course_ids": [""]}]),
    # The qid names output files: no path separator, nothing empty, no repeats.
    json.dumps([{**QUESTION, "qid": "a/b"}]), json.dumps([{**QUESTION, "qid": ""}]), json.dumps([QUESTION, QUESTION]),
])
def test_a_bad_questions_file_is_a_setup_error_before_any_request(questions_text, tmp_path, monkeypatch):
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: pytest.fail("no request for a bad questions file"))
    questions = tmp_path / "questions.json"
    questions.write_text(questions_text, encoding="utf-8")
    assert main(["--api-base", "http://api.test", "--out", str(tmp_path / "out"), "--questions", str(questions)]) == 2
    assert main(["--api-base", "http://api.test", "--out", str(tmp_path / "out"),
                 "--questions", str(tmp_path / "missing.json")]) == 2
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("response", [
    httpx.Response(503, text="busy"), httpx.Response(200, text="<html>not json</html>"),
    httpx.Response(200, json={"unexpected": True}),
])
def test_api_problems_are_setup_errors_before_any_model_call(response, tmp_path, monkeypatch):
    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: real_client(
        transport=httpx.MockTransport(lambda request: response), **kwargs))
    fake_model(monkeypatch, [])  # Any model call would raise StopIteration inside the run.
    assert main(["--api-base", "http://api.test", "--out", str(tmp_path / "out"), "--runs", "1"]) == 2
    assert not (tmp_path / "out").exists()


def test_an_out_path_that_cannot_be_a_folder_is_a_setup_error_before_any_model_call(tmp_path, monkeypatch):
    fake_api(monkeypatch)
    fake_model(monkeypatch, [])  # Any model call would raise StopIteration inside the run.
    taken = tmp_path / "taken"
    taken.write_text("a file", encoding="utf-8")
    assert main(["--api-base", "http://api.test", "--out", str(taken), "--runs", "1"]) == 2


def test_every_prompt_is_saved_before_the_first_model_call(tmp_path):
    seen = []

    def fake(prompt):
        seen.append(sorted(path.name for path in (tmp_path / "prompts").iterdir()))
        yield PLAIN

    run([QUESTION, {**QUESTION, "qid": "Q2"}], PAYLOADS, out=tmp_path, runs=1, max_calls=5, stream_fn=fake)
    assert seen[0] == ["Q1.context.json", "Q1.txt", "Q2.context.json", "Q2.txt"]


def test_a_bad_rescore_file_is_a_setup_error(tmp_path):
    assert main(["--rescore", str(tmp_path / "missing.json")]) == 2
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert main(["--rescore", str(broken)]) == 2
    run([QUESTION], PAYLOADS, out=tmp_path, runs=1, max_calls=1, stream_fn=lambda prompt: iter([PLAIN]))
    good = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    for change in ({"context": {"lang": "zh"}},  # A saved context missing its fields.
                   {"answer": ["not", "text"]}, {"context": {**good["records"][0]["context"], "extra": 1}}):
        odd = tmp_path / "odd.json"
        odd.write_text(json.dumps({**good, "records": [{**good["records"][0], **change}]}), encoding="utf-8")
        assert main(["--rescore", str(odd)]) == 2, change
    odd.write_text(json.dumps({key: value for key, value in good.items() if key != "chat_v4_sha256"}), encoding="utf-8")
    assert main(["--rescore", str(odd)]) == 2


def test_a_bug_in_the_checks_is_not_reported_as_a_setup_error(tmp_path, monkeypatch):
    import eval.answer_checks as checks  # noqa: PLC0415

    run([QUESTION], PAYLOADS, out=tmp_path, runs=1, max_calls=1, stream_fn=lambda prompt: iter([PLAIN]))

    def broken(text, context):
        raise TypeError("a bug in a check")

    monkeypatch.setattr(checks, "check_answer", broken)
    with pytest.raises(TypeError, match="a bug in a check"):
        main(["--rescore", str(tmp_path / "results.json")])


def test_main_redacts_the_configured_key_from_recorded_errors(tmp_path, monkeypatch):
    fake_api(monkeypatch)
    fake_model(monkeypatch, [RuntimeError("upstream rejected test-key-not-real")] * 5)
    assert main(["--api-base", "http://api.test", "--out", str(tmp_path), "--runs", "1"]) == 3
    saved = (tmp_path / "results.json").read_text(encoding="utf-8")
    assert "test-key-not-real" not in saved and "[REDACTED]" in saved


def test_context_flags_follow_the_evidence_both_ways():
    plain = {**payload(snapshot=False), "source_review_ids": ["syllabus_a"], "evidence_snippets": [],
             "workload_hours_per_week": None, "difficulty_score": None, "prereqs": []}
    _, context = build_case({**QUESTION, "course_ids": ["neu-cs-5800"]}, {"neu-cs-5800": plain})
    assert not context.has_rmp_data and not context.prereq_relevant and not context.fetch_date_relevant
    dated = payload()
    dated["answer_evidence"]["catalog"]["retrieved_at"] = "2026-10-01T00:00:00Z"
    _, context = build_case({**QUESTION, "course_ids": ["neu-cs-5800"]}, {"neu-cs-5800": dated})
    assert not context.fetch_date_relevant and not context.no_catalog_relevant
    program_prompt, _ = build_case({**QUESTION, "route": "program"}, PAYLOADS)
    alias_prompt, _ = build_case(QUESTION, PAYLOADS)
    # The rules name the code in both prompts; only the program route adds it to the course evidence.
    assert program_prompt.count("program_seed_unverified") > alias_prompt.count("program_seed_unverified")


def test_main_dry_run_uses_only_tagged_get_requests(tmp_path, monkeypatch):
    seen = []
    real_client = httpx.Client

    def handler(request):
        seen.append((request.method, request.headers.get("X-Eval-Run"), request.headers.get("User-Agent")))
        course_id = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json=payload(course_id, "CS " + course_id[-4:], "Course " + course_id[-4:]))

    monkeypatch.setattr(httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    assert main(["--api-base", "http://api.test", "--out", str(tmp_path), "--dry-run", "--eval-run", "tag-1"]) == 0
    assert seen and all(entry == ("GET", "tag-1", "neu-compass-answer-eval/1") for entry in seen)
    assert len(seen) == len({cid for question in DEFAULT_QUESTIONS for cid in question["course_ids"]})
    assert json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))["model_calls"] == 0


def test_default_questions_are_well_formed():
    for question in DEFAULT_QUESTIONS:
        assert set(question) == {"qid", "lang", "query", "course_ids", "route", "notices"}
        assert question["lang"] in {"zh", "en"} and question["route"] in {"alias", "hybrid", "program"}
    assert any(question["notices"] == ["program_schedule_unverified"] for question in DEFAULT_QUESTIONS)


def test_context_round_trips_through_results_json():
    from scripts.eval_answers_live import context_from_json, context_to_json  # noqa: PLC0415

    _, context = build_case(QUESTION, PAYLOADS)
    assert context_from_json(json.loads(json.dumps(context_to_json(context)))) == context


def test_rescore_rechecks_saved_answers_without_any_call(tmp_path, monkeypatch):
    """Tuning a detector must not need new model calls: --rescore re-checks the saved answers."""
    def fake(prompt):
        yield "这门课讲图算法。"

    run([QUESTION], PAYLOADS, out=tmp_path, runs=1, max_calls=1, stream_fn=fake)
    saved = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    saved["records"][0]["answer"] = "Leaked neu-cs-5800."  # As if the stored answer had been this.
    (tmp_path / "results.json").write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: pytest.fail("rescore must not open HTTP"))
    assert main(["--rescore", str(tmp_path / "results.json")]) == 1
    rescored = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert rescored["summary"]["ids_fail"] == 1 and rescored["model_calls"] == 1 and "rescored_utc" in rescored
    assert "| Q1 run 1 | ids_fail |" in (tmp_path / "summary.md").read_text(encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["--out", str(tmp_path)])  # --api-base is required unless --rescore is given.
