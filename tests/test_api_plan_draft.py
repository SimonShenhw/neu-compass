"""R4b: POST /programs/{program_id}/plans/{plan_id}/draft checks a session-only draft against one exact
source-checked plan, computing only. Synthetic courses and aliases plus the repository's curated plans; no model,
no network, no real data.
中文：R4b 草案核对接口：按一份确切的已核对方案核对只在会话里的草案，只计算。只用合成课程、合成别名和仓库里的策展方案，
不调模型、不联网、没有真实数据。
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import sqlite3

import pytest
import structlog
from fastapi.testclient import TestClient

from api.logging import configure_logging
from api.plan_draft import DraftCheckOut
from api.session_cookie import COOKIE_NAME
from app.text_render import literal_markdown
from db.alias_repository import AliasRepository
from db.program_plan_repository import ProgramPlanRepository, content_hash
from db.program_repository import ProgramRepository
from db.query_log_repository import QueryLogRepository
from db.repository import CourseRepository
from schemas.alias import Alias, AliasReviewStatus, AliasSource, AliasType
from schemas.course import Course, DeliveryMode
from schemas.plan_draft import DraftCourse, evaluate_draft
from schemas.program import Program
from schemas.program_plan import ProgramPlan
from tests.conftest import build_test_app
from tests.test_csrf_cors import ORIGIN, REFUSED, add_user, make_client
from tests.test_program_plan_links import plans

PLAN = plans()[0]  # cs-ms standard: source_checked, partial coverage. 中文：已核对、只记录了部分规则。
OTHER = plans()[1]  # a ds-ms plan, for "a plan of another program". 中文：别的项目的方案。
SHA = content_hash(PLAN)
URL = f"/programs/{PLAN.program_id}/plans/{PLAN.plan_id}/draft"
LONG_NAME = "Synthetic " + "x" * 491  # 501 characters: a Course may carry it, a DraftCourse may not.
ZZ = [f"ZZ {7001 + i}" for i in range(21)]
MARKER = "SYNTHETIC_PRIVATE_DRAFT_MARKER"


def add_course(conn, course_id: str, code: str, name: str, credits: int | None = 4) -> None:
    CourseRepository(conn).insert(Course(course_id=course_id, primary_code=code, primary_name=name,
                                         term="Fall 2026", credits=credits, delivery_mode=DeliveryMode.IN_PERSON),
                                  raw_text="synthetic course for the draft check")


def add_alias(conn, text: str, course_id: str, kind: AliasType = AliasType.CROSS_LISTED) -> None:
    AliasRepository(conn).add(Alias(alias_text=text, alias_type=kind, primary_course_id=course_id, confidence=1.0,
                                    source=AliasSource.MANUAL, review_status=AliasReviewStatus.APPROVED))


def library(conn) -> None:
    """The synthetic course library on top of conftest's (AAI 6600, CS 5800 with the alias "Algo", DS 5220).
    中文：在 conftest 的课程之上加的合成课程库。"""
    add_course(conn, "c-cs-5010", "CS 5010", "Programming Design Paradigm")
    add_course(conn, "c-cs-5200", "CS 5200", "Database Management Systems")
    add_course(conn, "c-cs-5100", "CS 5100", "Foundations of Artificial Intelligence", credits=None)
    add_course(conn, "c-cs-7140", "CS 7140", "Advanced Machine Learning")
    add_course(conn, "c-eece-7397", "EECE 7397", "Advanced Machine Learning")
    add_alias(conn, "CS 7140", "c-eece-7397")  # cross-listed both ways. 中文：互为交叉列出。
    add_alias(conn, "EECE 7397", "c-cs-7140")
    add_course(conn, "c-xla-7001", "XLA 7001", "Synthetic one-way cross-listing A")
    add_course(conn, "c-xlb-7002", "XLB 7002", "Synthetic one-way cross-listing B")
    add_alias(conn, "XLB 7002", "c-xla-7001")  # only A's record names B. 中文：只有 A 的记录写了 B。
    add_alias(conn, "CS 5810", "c-cs-5800", AliasType.RENAME)  # renumbered. 中文：改过课号。
    for i in range(12):  # one ref, twelve courses: ambiguous. 中文：一个引用对上十二门课。
        add_course(conn, f"c-amb-{i:02d}", f"AMB {6001 + i}", f"Synthetic ambiguous {i:02d}")
        add_alias(conn, "CS 6999", f"c-amb-{i:02d}", AliasType.SLANG)
    add_course(conn, "c-lng-6000", "LNG 6000", LONG_NAME)
    for i, code in enumerate(ZZ):
        add_course(conn, f"c-zz-{i:02d}", code, f"Synthetic filler {i:02d}")
    programs = ProgramRepository(conn)
    programs.upsert_program(Program(program_id="cs-ms", full_name="Synthetic CS", prefix="CS"))
    programs.upsert_program(Program(program_id="ds-ms", full_name="Synthetic DS", prefix="DS"))
    ProgramPlanRepository(conn).store(PLAN)
    ProgramPlanRepository(conn).store(OTHER)
    conn.commit()


@pytest.fixture
def real_logging():
    configure_logging()


@pytest.fixture
def client(empty_db: sqlite3.Connection):
    app = build_test_app(empty_db, seed=True)
    library(empty_db)
    with TestClient(app) as c:
        yield c


def check(client, *, ids=(), text=None, sha=SHA, url=URL):
    body = {"plan_content_sha256": sha, "course_ids": list(ids)}
    if text is not None:
        body["input"] = text
    return client.post(url, json=body)


def notices(response):
    return [(n["kind"], n["level"], n["text"]) for n in response.json()["notices"]]


def codes(response):
    return [c["code"] for c in response.json()["courses"]]


# === The answer ===


def test_a_guest_adds_codes_and_gets_the_server_draft_and_the_plan_evaluation(client):
    r = check(client, ids=["c-cs-5800"], text="cs5010, CS-5200\nCS 5100.")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    body = r.json()
    assert DraftCheckOut.model_validate(body).model_dump(mode="json") == body
    assert codes(r) == ["CS 5800", "CS 5010", "CS 5200", "CS 5100"]
    assert body["added"] == ["CS 5010", "CS 5200", "CS 5100"] and body["notices"] == []
    assert body["courses"][3] == {"course_id": "c-cs-5100", "code": "CS 5100",
                                  "name": "Foundations of Artificial Intelligence", "credits": None}
    assert body["plan_content_sha256"] == SHA
    courses = [DraftCourse(**c) for c in body["courses"]]
    assert body["result"] == evaluate_draft(PLAN, courses).model_dump(mode="json")


def test_without_input_the_draft_is_only_reread_and_reevaluated(client):
    r = check(client, ids=["c-cs-5100", "c-cs-5010"])
    assert r.status_code == 200 and codes(r) == ["CS 5100", "CS 5010"]
    assert r.json()["added"] == [] and r.json()["notices"] == []
    assert check(client, ids=["c-cs-5100", "c-cs-5010"], text="").json() == r.json()
    empty = check(client).json()
    assert empty["courses"] == [] and empty["result"] == evaluate_draft(PLAN, []).model_dump(mode="json")


def edit_record(conn, course_id: str, change) -> None:
    """Rewrite one stored course record, the way a catalog update (or a newer build) would. 中文：改一条存的课程记录。"""
    row = conn.execute("SELECT generated_json FROM courses WHERE course_id=?", (course_id,)).fetchone()
    conn.execute("UPDATE courses SET generated_json=? WHERE course_id=?",
                 (json.dumps(change(json.loads(row["generated_json"]))), course_id))
    conn.commit()


def test_the_sent_draft_is_reread_with_the_current_names_and_credits(client, empty_db):
    first = check(client, ids=["c-cs-5010", "c-cs-5100"]).json()["courses"]
    assert first == [{"course_id": "c-cs-5010", "code": "CS 5010", "name": "Programming Design Paradigm", "credits": 4},
                     {"course_id": "c-cs-5100", "code": "CS 5100", "name": "Foundations of Artificial Intelligence",
                      "credits": None}]
    edit_record(empty_db, "c-cs-5010", lambda data: data | {"primary_name": "Programming Design Paradigm (renamed)",
                                                            "credits": 2})
    later = check(client, ids=["c-cs-5010", "c-cs-5100"])
    assert later.json()["courses"][0] == {"course_id": "c-cs-5010", "code": "CS 5010",
                                          "name": "Programming Design Paradigm (renamed)", "credits": 2}
    assert later.json()["notices"] == [] and later.json()["courses"][1] == first[1]


@pytest.mark.parametrize("change", [lambda data: {"not": "a course"}, lambda data: data | {"future_field": 1}],
                         ids=["not-a-course", "newer-schema"])
def test_a_sent_course_whose_record_no_longer_reads_leaves_with_a_notice(client, empty_db, change):
    edit_record(empty_db, "c-cs-5010", change)
    r = check(client, ids=["c-cs-5010", "c-cs-5200"])
    assert r.status_code == 200
    assert notices(r) == [("invalid_record", "warning", "草案里有 1 门课的课程记录无法读取，已从草案移除。")]
    assert [c["course_id"] for c in r.json()["courses"]] == ["c-cs-5200"]
    typed = check(client, ids=["c-cs-5200"], text="CS 5010")  # typed instead: refused by code. 中文：改成输入。
    assert notices(typed) == [("invalid_record", "warning", "CS 5010 返回的课程身份或字段无效，未加入。")]


# === Notices: each kind with its exact sentence ===


def test_more_than_twenty_codes_add_nothing_and_check_nothing(client):
    r = check(client, text=" ".join(ZZ) + " Q1")
    assert notices(r) == [("too_many_codes", "warning", "一次最多填写 20 门；本次没有加入课程。")]
    assert codes(r) == [] and r.json()["added"] == []
    twenty = check(client, text=" ".join(ZZ[:20]))  # exactly twenty are all checked. 中文：正好 20 门都核对。
    assert notices(twenty) == [] and twenty.json()["added"] == ZZ[:20]


def test_badly_formatted_tokens_ten_by_name_then_a_count(client):
    r = check(client, text=" ".join(f"Q{i}" for i in range(1, 13)) + " CS5010")
    assert notices(r) == [("invalid_format", "warning", f"课号格式不正确，未加入：Q{i}") for i in range(1, 11)] + [
        ("invalid_format_more", "warning", "另有 2 项格式不正确；未加入。")]
    assert codes(r) == ["CS 5010"]
    ten = check(client, text=" ".join(f"Q{i}" for i in range(1, 11)))  # ten by name, no count line. 中文：正好 10 个。
    assert notices(ten) == [("invalid_format", "warning", f"课号格式不正确，未加入：Q{i}") for i in range(1, 11)]


def test_a_bad_token_is_named_as_typed_up_to_two_hundred_characters(client):
    long_token = "Q" + "x" * 299
    assert notices(check(client, text=long_token)) == [
        ("invalid_format", "warning", "课号格式不正确，未加入：" + long_token[:200])]
    # Five letters are not a subject, so they do not join the number. 中文：五个字母不算学科，不和数字连成课号。
    assert notices(check(client, text="ABCDE 5010")) == [("invalid_format", "warning", "课号格式不正确，未加入：ABCDE"),
                                                         ("invalid_format", "warning", "课号格式不正确，未加入：5010")]


def test_codes_already_in_the_draft_are_an_info_line(client):
    r = check(client, ids=["c-cs-5800"], text="CS5800 cs-5800")
    assert notices(r) == [("all_present", "info", "这些课号已在草案里，不会重复加入。")]
    assert codes(r) == ["CS 5800"]


def test_input_without_a_code_in_it_says_nothing_about_the_draft(client):
    r = check(client, ids=["c-cs-5800"], text="Q1")
    assert notices(r) == [("invalid_format", "warning", "课号格式不正确，未加入：Q1")] and codes(r) == ["CS 5800"]
    blank = check(client, ids=["c-cs-5800"], text=" \n ")  # not empty, so it goes through the add flow. 中文：不是空串。
    assert notices(blank) == [] and codes(blank) == ["CS 5800"] and blank.json()["added"] == []


def test_going_over_twenty_checks_nothing_and_says_by_how_much(client):
    r = check(client, ids=[f"c-zz-{i:02d}" for i in range(19)], text="CS 5010 CS 5200")
    assert notices(r) == [("over_limit", "warning", "草案最多 20 门，本次尚未核对；请从输入减少 1 门，或从草案移除至少 1 门。")]
    assert len(codes(r)) == 19 and r.json()["added"] == []
    assert check(client, ids=[f"c-zz-{i:02d}" for i in range(18)], text="CS 5010 CS 5200").json()["added"] == [
        "CS 5010", "CS 5200"]


def test_unknown_and_ambiguous_codes_are_not_added(client):
    r = check(client, text="CS 9999 CS 6999 CS 5010")
    assert notices(r) == [("not_found", "warning", "没有找到 CS 9999；未加入。"),
                          ("ambiguous", "warning", "对上多门，未加入；请核对完整课号：CS 6999")]
    ambiguous = r.json()["notices"][1]
    assert [c["code"] for c in ambiguous["candidates"]] == [f"AMB {6001 + i}" for i in range(10)]
    assert ambiguous["candidates"][0]["name"] == "Synthetic ambiguous 00" and ambiguous["candidates_omitted"] == 2
    assert codes(r) == ["CS 5010"]
    assert all(n["candidates"] == [] and n["candidates_omitted"] == 0 for n in r.json()["notices"][:1])


def test_a_cross_listed_pair_counts_once_under_the_first_code(client):
    r = check(client, text="CS 7140, EECE 7397")
    assert notices(r) == [
        ("also_matches", "warning", "按输入主课号核对 CS 7140；同一引用也匹配 EECE 7397（可能交叉列出）；方案按哪个课号算，请向项目核实。"),
        ("cross_listed_twin", "warning", "EECE 7397 和 CS 7140 可能是同一门交叉列出的课，只按 CS 7140 计入；如果是两门不同的课，请向项目核实。")]
    assert codes(r) == ["CS 7140"]
    later = check(client, ids=["c-cs-7140"], text="EECE 7397")
    assert notices(later) == [
        ("cross_listed_twin", "warning", "EECE 7397 和 CS 7140 可能是同一门交叉列出的课，只按 CS 7140 计入；如果是两门不同的课，请向项目核实。")]
    assert codes(later) == ["CS 7140"]


def test_a_one_way_cross_listing_counts_once_in_either_order(client):
    # Only XLA 7001's record names XLB 7002: "XLB 7002" finds both courses, "XLA 7001" only its own.
    # 中文：只有 XLA 7001 的记录写了 XLB 7002：输入「XLB 7002」找到两门，输入「XLA 7001」只找到自己。
    b_first = check(client, text="XLB 7002, XLA 7001")
    assert notices(b_first) == [
        ("also_matches", "warning", "按输入主课号核对 XLB 7002；同一引用也匹配 XLA 7001（可能交叉列出）；方案按哪个课号算，请向项目核实。"),
        ("cross_listed_twin", "warning", "XLA 7001 和 XLB 7002 可能是同一门交叉列出的课，只按 XLB 7002 计入；如果是两门不同的课，请向项目核实。")]
    assert codes(b_first) == ["XLB 7002"]
    a_first = check(client, text="XLA 7001, XLB 7002")
    assert notices(a_first) == [
        ("cross_listed_twin", "warning", "XLB 7002 和 XLA 7001 可能是同一门交叉列出的课，只按 XLA 7001 计入；如果是两门不同的课，请向项目核实。")]
    assert codes(a_first) == ["XLA 7001"]


def test_a_renumbered_code_is_checked_under_its_primary_code(client):
    r = check(client, text="CS 5810")
    assert notices(r) == [("primary_code", "warning", "输入的 CS 5810 对应主课号 CS 5800，按 CS 5800 核对；方案按哪个课号算，请向项目核实。")]
    assert codes(r) == ["CS 5800"] and r.json()["added"] == ["CS 5800"]
    again = check(client, ids=["c-cs-5800"], text="CS 5810")
    assert notices(again)[-1] == ("nothing_new", "info", "没有新增课程；重复课号不会重复加入。")
    assert codes(again) == ["CS 5800"] and again.json()["added"] == []


def test_an_old_code_of_a_course_already_there_adds_only_the_new_courses(client):
    primary = ("primary_code", "warning", "输入的 CS 5810 对应主课号 CS 5800，按 CS 5800 核对；方案按哪个课号算，请向项目核实。")
    r = check(client, ids=["c-cs-5800"], text="CS 5810 CS 5010")
    assert notices(r) == [primary]
    assert codes(r) == ["CS 5800", "CS 5010"] and r.json()["added"] == ["CS 5010"]
    both = check(client, text="CS 5810 CS 5800")  # one course under its old and its new code. 中文：新旧课号同一门。
    assert notices(both) == [primary]
    assert codes(both) == ["CS 5800"] and both.json()["added"] == ["CS 5800"]


def test_a_record_the_draft_cannot_hold_is_refused_by_code(client):
    r = check(client, text="LNG 6000 CS 5010")
    assert notices(r) == [("invalid_record", "warning", "LNG 6000 返回的课程身份或字段无效，未加入。")]
    assert codes(r) == ["CS 5010"]


def test_a_course_whose_id_the_request_would_refuse_is_not_taken(client, empty_db):
    # The page could never send this ID back (the request model refuses it), so it never enters the draft.
    # 中文：页面没法把这个 ID 发回来（请求模型不收），所以它不进草案。
    add_course(empty_db, "c bad/id", "BAD 6001", "Synthetic course with an odd ID")
    empty_db.commit()
    r = check(client, text="BAD 6001 CS 5010")
    assert notices(r) == [("invalid_record", "warning", "BAD 6001 返回的课程身份或字段无效，未加入。")]
    assert codes(r) == ["CS 5010"]


def test_the_sent_draft_loses_gone_invalid_and_doubled_records_with_a_notice_each(client, empty_db):
    # A second record under the same code (only here: it would make every "CS 5010" input ambiguous).
    # 中文：同一课号的第二条记录（只放在这里：否则所有「CS 5010」输入都会对上两门）。
    add_course(empty_db, "c-cs-5010-copy", "CS 5010", "Programming Design Paradigm (second record)")
    empty_db.commit()
    r = check(client, ids=["c-cs-5010", "c-gone-1", "c-lng-6000", "c-cs-5010-copy", "c-gone-2", "c-cs-5200"])
    gone = ("course_gone", "warning", "草案里有 1 门课在课程记录里找不到了，已从草案移除。")
    assert notices(r) == [gone,
                          ("invalid_record", "warning", "草案里的 LNG 6000 课程身份或字段无效，已从草案移除。"),
                          ("duplicate_code", "warning", "草案里有两门课现在是同一个课号 CS 5010，只保留一门。"),
                          gone]  # one line per course, so two gone courses are two lines. 中文：每门一行。
    assert [c["course_id"] for c in r.json()["courses"]] == ["c-cs-5010", "c-cs-5200"]


# === The same input, the same words as the Streamlit page ===


class _ApiViaTestClient:
    """app.api_client.ApiClient's two reads, answered by the same app and database. 中文：同一个应用和库回答的两次读取。"""

    def __init__(self, client):
        self.client = client

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def resolve_course(self, ref):
        response = self.client.get("/resolve/course", params={"ref": ref})
        assert response.status_code == 200
        return response.json()

    def get_course(self, course_id):
        response = self.client.get(f"/course/{course_id}")
        assert response.status_code == 200
        return response.json()


class _St:
    def __init__(self, existing):
        self.lines, self.session_state = [], {"plan_draft_courses": [c.model_dump() for c in existing]}

    def warning(self, value):
        self.lines.append(("warning", value))

    def info(self, value):
        self.lines.append(("info", value))

    def text(self, value):
        self.lines.append(("text", value))

    def caption(self, value):
        self.lines.append(("caption", value))

    def spinner(self, _):
        return contextlib.nullcontext()


# Streamlit wraps these in literal_markdown (they quote a code or a name); the others are fixed sentences.
# 中文：Streamlit 用 literal_markdown 包住这些（里面有课号或课名），其余是固定句子。
WRAPPED = {"invalid_format", "not_found", "ambiguous", "cross_listed_twin", "also_matches", "primary_code",
           "invalid_record"}


def as_streamlit(answer):
    lines = []
    for n in answer["notices"]:
        lines.append((n["level"], literal_markdown(n["text"]) if n["kind"] in WRAPPED else n["text"]))
        lines += [("text", c["code"] + " · " + c["name"]) for c in n["candidates"]]
        if n["candidates_omitted"]:
            lines.append(("caption", f"另有 {n['candidates_omitted']} 个候选未展开。"))
    return lines


def same_as_streamlit(client, monkeypatch, ids, text):
    """Streamlit's `_add` on the same draft and input, reading the same app and database, shows the API's notices
    and ends with the API's draft. 中文：Streamlit 的 `_add` 在同样的草案和输入上、读同一个应用和库，显示的提示和
    最后的草案都和 API 一样。"""
    import app.api_client as clients
    from app.plan_draft_view import _add

    answer = check(client, ids=ids, text=text).json()
    existing = [DraftCourse(**c) for c in check(client, ids=ids).json()["courses"]]
    monkeypatch.setattr(clients, "ApiClient", lambda **kwargs: _ApiViaTestClient(client))
    st = _St(existing)
    _add(st, text, existing)
    assert st.lines == as_streamlit(answer)
    assert st.session_state["plan_draft_courses"] == answer["courses"]


@pytest.mark.parametrize("ids,text", [
    ([], " ".join(f"Q{i}" for i in range(1, 13)) + " CS5010"),
    ([], " ".join(f"Q{i}" for i in range(1, 11))),
    (["c-cs-5800"], "Q1"),
    (["c-cs-5800"], " \n "),
    ([], " ".join(ZZ)),
    ([], " ".join(ZZ[:20])),
    (["c-cs-5800"], "CS5800"),
    ([f"c-zz-{i:02d}" for i in range(19)], "CS 5010 CS 5200"),
    ([], "CS 9999 CS 6999 CS 7140 EECE 7397 CS 5810 LNG 6000 CS 5010 CS 5100"),
    (["c-cs-5800"], "CS 5810"),
    (["c-cs-5800"], "CS 5810 CS 5010"),
    ([], "CS 5810 CS 5800"),
    (["c-cs-7140"], "EECE 7397 CS 5200"),
    ([], "XLB 7002, XLA 7001"),
    ([], "XLA 7001, XLB 7002"),
])
def test_the_api_says_what_the_streamlit_page_says_and_keeps_the_same_draft(client, monkeypatch, ids, text):
    same_as_streamlit(client, monkeypatch, ids, text)


def test_two_records_under_the_typed_code_are_ambiguous_on_both_pages(client, empty_db, monkeypatch):
    add_course(empty_db, "c-cs-5010-copy", "CS 5010", "Programming Design Paradigm (second record)")
    empty_db.commit()
    r = check(client, text="CS 5010")
    assert notices(r) == [("ambiguous", "warning", "对上多门，未加入；请核对完整课号：CS 5010")]
    assert [(c["code"], c["name"]) for c in r.json()["notices"][0]["candidates"]] == [
        ("CS 5010", "Programming Design Paradigm"), ("CS 5010", "Programming Design Paradigm (second record)")]
    assert codes(r) == []
    same_as_streamlit(client, monkeypatch, [], "CS 5010")


def test_also_matches_names_at_most_ten_other_codes_once_each(client, empty_db, monkeypatch):
    # "AMB 6001" is also an alias of the eleven other AMB courses and of a second AMB 6003 record.
    # 中文：「AMB 6001」也是另外 11 门 AMB 课和第二条 AMB 6003 记录的别名。
    add_course(empty_db, "c-amb-02-copy", "AMB 6003", "Synthetic ambiguous 02 (second record)")
    add_alias(empty_db, "AMB 6001", "c-amb-02-copy")
    for i in range(1, 12):
        add_alias(empty_db, "AMB 6001", f"c-amb-{i:02d}")
    empty_db.commit()
    r = check(client, text="AMB 6001")
    # In the alias lookup's order (the second AMB 6003 record's alias was stored first); AMB 6003 once; AMB 6012 cut.
    # 中文：按别名查询返回的顺序（第二条 AMB 6003 记录的别名先存）；AMB 6003 只出现一次；AMB 6012 被截掉。
    others = "、".join(["AMB 6003", "AMB 6002", *(f"AMB {6004 + i}" for i in range(8))])
    assert notices(r) == [("also_matches", "warning", "按输入主课号核对 AMB 6001；同一引用也匹配 " + others
                           + "（可能交叉列出）；方案按哪个课号算，请向项目核实。")]
    assert codes(r) == ["AMB 6001"]
    same_as_streamlit(client, monkeypatch, [], "AMB 6001")


def test_a_code_cross_listed_with_two_accepted_courses_names_the_first(client, empty_db, monkeypatch):
    # TWC 7103's record answers to TWA 7101 and TWB 7102; its own code finds only itself.
    # 中文：TWC 7103 的记录也对得上 TWA 7101 和 TWB 7102；输入它自己的课号只找到它。
    for course_id, code in [("c-twa", "TWA 7101"), ("c-twb", "TWB 7102"), ("c-twc", "TWC 7103")]:
        add_course(empty_db, course_id, code, "Synthetic three-way cross-listing " + code)
    add_alias(empty_db, "TWA 7101", "c-twc")
    add_alias(empty_db, "TWB 7102", "c-twc")
    empty_db.commit()
    r = check(client, text="TWA 7101, TWB 7102, TWC 7103")
    assert notices(r)[-1] == ("cross_listed_twin", "warning", "TWC 7103 和 TWA 7101 可能是同一门交叉列出的课，只按 "
                              "TWA 7101 计入；如果是两门不同的课，请向项目核实。")
    assert codes(r) == ["TWA 7101", "TWB 7102"]
    same_as_streamlit(client, monkeypatch, [], "TWA 7101, TWB 7102, TWC 7103")


# === The plan: exact version or a 409 with a reason ===


def conflict(response, reason):
    assert response.status_code == 409 and response.headers["cache-control"] == "no-store"
    body = response.json()
    assert set(body) == {"detail", "error_type", "status_code", "reason"}
    assert body["error_type"] == "conflict" and body["status_code"] == 409 and body["reason"] == reason
    assert MARKER not in response.text
    return body


def test_a_stale_content_version_is_a_409_and_computes_nothing(client, monkeypatch):
    import api.routes.program as routes

    def refuse(*args, **kwargs):
        raise AssertionError("checked a draft for a refused plan")

    monkeypatch.setattr(routes, "check_draft", refuse)
    body = conflict(check(client, text="CS 5010 " + MARKER, sha="0" * 64), "stale")
    assert body["detail"] == "The selected plan's scope or content version has changed."


def test_an_unknown_plan_or_one_of_another_program_is_missing(client):
    assert conflict(check(client, url="/programs/cs-ms/plans/cs-ms-no-such-plan/draft"), "missing")["detail"] == \
        "The selected plan is not available."
    conflict(check(client, url=f"/programs/cs-ms/plans/{OTHER.plan_id}/draft", sha=content_hash(OTHER)), "missing")
    assert check(client, url=f"/programs/ds-ms/plans/{OTHER.plan_id}/draft", sha=content_hash(OTHER)).status_code == 200


def test_another_programs_plan_is_missing_even_when_its_row_is_broken(client, empty_db):
    empty_db.execute("UPDATE program_plans SET document='{}' WHERE plan_id=?", (OTHER.plan_id,))
    empty_db.commit()
    conflict(check(client, url=f"/programs/cs-ms/plans/{OTHER.plan_id}/draft", sha=content_hash(OTHER)), "missing")
    conflict(check(client, url=f"/programs/ds-ms/plans/{OTHER.plan_id}/draft", sha=content_hash(OTHER)), "unusable")


def test_a_plan_not_checked_against_its_sources_is_refused(client, empty_db):
    draft = ProgramPlan.model_validate(PLAN.model_dump() | {"review_status": "draft"})
    ProgramPlanRepository(empty_db).store(draft, allow_downgrade=True)
    empty_db.commit()
    assert conflict(check(client, sha=content_hash(draft)), "draft")["detail"] == \
        "The selected plan has not been checked against its sources."


def test_an_unverifiable_plan_is_unusable(client, empty_db):
    empty_db.execute("UPDATE program_plans SET document='{}' WHERE plan_id=?", (PLAN.plan_id,))
    empty_db.commit()
    assert conflict(check(client), "unusable")["detail"] == "The selected plan cannot be verified."


def test_plans_that_cannot_be_read_now_are_unavailable(client, monkeypatch):
    monkeypatch.setattr(ProgramPlanRepository, "available", lambda self: False)
    assert conflict(check(client), "unavailable")["detail"] == "The selected plan cannot be checked right now."


def test_a_plan_read_error_is_unavailable_too(client, monkeypatch):
    def broken(self, selection):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(ProgramPlanRepository, "resolve_selection", broken)
    conflict(check(client), "unavailable")


@pytest.mark.parametrize("target,name", [(CourseRepository, "get_batch"), (AliasRepository, "resolve"),
                                         (ProgramRepository, "get_program")])
def test_a_course_or_program_read_error_is_a_503_that_echoes_nothing(client, real_logging, caplog, monkeypatch,
                                                                     target, name):
    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked " + MARKER)

    monkeypatch.setattr(target, name, broken)
    with caplog.at_level(logging.INFO):
        r = check(client, ids=["c-cs-5010"], text="CS 5200 " + MARKER)
    assert r.status_code == 503 and r.headers["cache-control"] == "no-store"
    assert r.json() == {"detail": "The course records cannot be read right now.", "error_type": "service_unavailable",
                        "status_code": 503}
    assert "draft.storage_failed" in caplog.text and "OperationalError" in caplog.text
    assert all(value not in caplog.text + r.text for value in [MARKER, "CS 5200", "c-cs-5010"])


def test_an_unknown_program_is_the_usual_404(client):
    r = check(client, url=f"/programs/zz-ms/plans/{PLAN.plan_id}/draft")
    assert r.status_code == 404 and r.json() == {"detail": "program_id not found", "error_type": "not_found",
                                                 "status_code": 404}


@pytest.mark.parametrize("change", [
    {"course_ids": [f"c-zz-{i:02d}" for i in range(21)]},
    {"course_ids": ["c-cs-5010", "c-cs-5010"]},
    {"course_ids": ["../" + MARKER]},
    {"course_ids": "c-cs-5010"},
    {"input": "x" * 4001},
    {"input": 5010},
    {"plan_content_sha256": "F" * 64},
    {"plan_content_sha256": None},
    {"extra": MARKER},
])
def test_a_body_out_of_bounds_is_a_422_that_echoes_nothing(client, change):
    body = {"plan_content_sha256": SHA, "course_ids": []} | change
    r = client.post(URL, json=body)
    assert r.status_code == 422 and r.json()["error_type"] == "invalid_input"
    assert MARKER not in r.text and "xxxxxxxx" not in r.text


@pytest.mark.parametrize("url", ["/programs/CS-MS/plans/x/draft", f"/programs/cs-ms/plans/{'a' * 101}/draft",
                                 "/programs/cs-ms/plans/Plan_1/draft"])
def test_path_ids_outside_the_plan_id_patterns_are_a_422(client, url):
    assert check(client, url=url).status_code == 422


def test_exactly_twenty_ids_and_four_thousand_characters_are_accepted(client):
    r = check(client, ids=[f"c-zz-{i:02d}" for i in range(20)], text="CS5010 " + "," * 3993)
    assert r.status_code == 200 and len(codes(r)) == 20
    assert notices(r) == [("over_limit", "warning", "草案最多 20 门，本次尚未核对；请从输入减少 1 门，或从草案移除至少 1 门。")]


# === plan_revisions: the version the page sends back ===


def test_curriculum_and_plans_answers_name_each_plans_content_version(client):
    curriculum = client.get("/programs/cs-ms").json()
    listed = client.get("/programs/cs-ms/plans").json()
    assert curriculum["plan_revisions"] == listed["plan_revisions"] == {PLAN.plan_id: SHA}
    assert [p["plan_id"] for p in curriculum["plans"]] == [PLAN.plan_id]
    assert "plan_content_sha256" not in curriculum["plans"][0]
    assert check(client, sha=curriculum["plan_revisions"][PLAN.plan_id], text="CS 5010").status_code == 200
    assert client.get("/programs/ds-ms").json()["plan_revisions"] == {OTHER.plan_id: content_hash(OTHER)}


def test_revisions_name_every_listed_plan_and_follow_the_filters(client, empty_db):
    align = plans()[5]  # cs-ms align, source-checked. 中文：已核对。
    bridge = ProgramPlan.model_validate(align.model_dump() | {  # a draft plan is listed too. 中文：草稿方案也列出。
        "plan_id": "cs-ms-boston-2026-2027-bridge", "pathway": "bridge", "review_status": "draft",
        "checked_by": None, "checked_on": None})
    for item in (align, bridge):
        ProgramPlanRepository(empty_db).store(item)
    empty_db.commit()
    want = {item.plan_id: content_hash(item) for item in (PLAN, align, bridge)}
    curriculum = client.get("/programs/cs-ms").json()
    assert curriculum["plan_revisions"] == want and {p["plan_id"] for p in curriculum["plans"]} == set(want)
    assert client.get("/programs/cs-ms/plans").json()["plan_revisions"] == want
    filtered = client.get("/programs/cs-ms/plans", params={"pathway": "align"}).json()
    assert [p["plan_id"] for p in filtered["plans"]] == [align.plan_id]
    assert filtered["plan_revisions"] == {align.plan_id: want[align.plan_id]}


def test_a_program_without_plans_has_empty_revisions(client, empty_db):
    ProgramRepository(empty_db).upsert_program(Program(program_id="pjm-ms", full_name="Synthetic PJM", prefix="PJM"))
    empty_db.commit()
    assert client.get("/programs/pjm-ms").json()["plan_revisions"] == {}
    assert client.get("/programs/pjm-ms/plans").json()["plan_revisions"] == {}


# === Privacy and writes ===


def test_no_course_code_id_or_typed_text_reaches_the_logs_and_nothing_is_written(client, empty_db, real_logging,
                                                                             caplog):
    before = empty_db.total_changes
    with caplog.at_level(logging.INFO):
        r = check(client, ids=["c-cs-5800"], text=f"CS 5010, CS 7140 EECE 7397 {MARKER}")
    assert r.status_code == 200 and r.json()["added"] == ["CS 5010", "CS 7140"]
    assert empty_db.total_changes == before and QueryLogRepository(empty_db).count() == 0
    for value in ["CS 5010", "CS 7140", "EECE 7397", "CS 5800", "c-cs-5010", "c-cs-7140", "c-cs-5800", MARKER,
                  "Programming Design Paradigm"]:
        assert value not in caplog.text
    checked = next(line for line in caplog.text.splitlines() if "draft.checked" in line)
    # The counts survive the allowlist: 3 courses, 2 added, 3 notices (bad token, also matches, twin).
    # 中文：计数过得了白名单：3 门课、加了 2 门、3 条提示（格式不对、也匹配、交叉列出）。
    assert all(re.search(key + r"\W{1,4}" + count + r"\b", checked)
               for key, count in [("courses", "3"), ("added", "2"), ("notices", "3")])
    assert "request.handled" in caplog.text


def test_a_refused_plan_logs_its_outcome_but_no_course(client, real_logging, caplog):
    with caplog.at_level(logging.INFO):
        conflict(check(client, ids=["c-cs-5800"], text="CS 5010 " + MARKER, sha="0" * 64), "stale")
    refused = next(line for line in caplog.text.splitlines() if "draft.plan_selection" in line)
    assert re.search(r"plan_outcome\W{1,4}stale\b", refused)
    assert re.search(r"plan_id\W{1,4}" + re.escape(PLAN.plan_id), refused)
    assert all(value not in caplog.text for value in ["CS 5010", "c-cs-5800", MARKER])


def test_a_nested_log_line_on_the_draft_route_keeps_only_allowlisted_fields(client, real_logging, caplog,
                                                                            monkeypatch):
    # A debug line someone might add to the shared lookup code later: the course-read allowlist strips its values.
    # 中文：以后有人可能在共用的查找代码里加的一行日志：课程读的白名单把它的值去掉。
    original = AliasRepository.resolve

    def chatty(self, term):
        structlog.get_logger("neu_compass.alias").info("alias.resolve", term=term, courses=["c-cs-5010"], count=1)
        return original(self, term)

    monkeypatch.setattr(AliasRepository, "resolve", chatty)
    with caplog.at_level(logging.INFO):
        assert check(client, text="CS 5010").status_code == 200
    assert "alias.resolve" in caplog.text and "draft.checked" in caplog.text
    assert "CS 5010" not in caplog.text and "c-cs-5010" not in caplog.text


# === Session cookie: the R2a cross-site check applies; guests need no headers ===


def test_a_cookie_bearing_check_needs_the_front_ends_signs(empty_db, monkeypatch):
    client = make_client(empty_db, monkeypatch, seed=True)
    library(empty_db)
    client.cookies.set(COOKIE_NAME, add_user(empty_db), domain="testserver.local")
    with client:
        refused = check(client, text="CS 5010")
        assert refused.status_code == 403 and refused.json() == REFUSED
        r = client.post(URL, json={"plan_content_sha256": SHA, "course_ids": [], "input": "CS 5010"},
                        headers={"Origin": ORIGIN, "X-NEU-Compass": "1"})
        assert r.status_code == 200 and r.json()["added"] == ["CS 5010"]


# === One home for the input parser ===


def test_streamlit_and_the_api_read_input_with_the_same_function():
    import app.plan_draft_view as view
    import schemas.plan_draft as shared

    assert view.parse_course_codes is shared.parse_course_codes
