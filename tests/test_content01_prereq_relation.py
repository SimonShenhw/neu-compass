"""CONTENT-01 (the 2026-11-01 live acceptance): asked what CS 6140 covers, an answer said its prerequisites are "CS 5800
或 CS 7800" and took it back only at its end, while the record had them as a flat list whose AND/OR is not recorded.
Offline, from the repository's catalog fixture: what prompt 4.6 gives the model for such a course, and the checks on
that answer, on the wording the prompt asks for, and on a course whose rule is a year rule. No network, no model.

中文：CONTENT-01（2026-11-01 线上验收）：问 CS 6140 学什么，回答先说先修是「CS 5800 或 CS 7800」，到结尾才收回；而记录里
只有 AND/OR 没有记录的平铺列表。离线、用仓库的目录夹具：4.6 提示词给这种课的内容，以及对那条回答、提示词要的说法和有年度
规则的课的检查。不联网、不调模型。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from db.catalog_source_repository import CatalogSourceRepository
from eval.answer_checks import HARD_FAILURES, check_answer
from llm.prompts.chat_v4 import FLAT_PREREQS_KEY, build_prompt, format_courses_block
from rag.answer_evidence import course_answer_evidence
from rag.retriever import SearchHit
from schemas.answer_evidence import RequisiteEdition, RequisiteEvidence, RequisiteSectionEvidence
from schemas.course import Course
from scrapers.neu_catalog import _parse_dept_html
from scripts.eval_answers_live import context_from_records

CS = "https://catalog.northeastern.edu/course-descriptions/cs/"
FIXTURE = Path(__file__).parent / "fixtures/neu_catalog/dept_cs.html"
QUERY = "CS 6140 主要学什么？请用两三句话概括，并指出适合什么基础的学生。"
# The live answer as far as the acceptance screenshot shows it (its tail after 「建议」 is cut off there).
# 中文：验收截图里能看到的那部分线上回答（「建议」之后截图里看不到）。
LIVE_ANSWER = (
    "CS 6140 机器学习课程主要探讨机器学习和数据挖掘的多种技术，涵盖监督学习（如决策树、神经网络、支持向量机）、"
    "无监督学习和强化学习方法。课程还涉及计算学习理论和学习算法的性能分析，并包含一个编程项目。\n\n"
    f"根据 [NEU 官方课程目录]({CS})，该课程的先决条件是 CS 5800 或 CS 7800。因此，它适合已完成或熟悉这些课程内容的同学。\n\n"
    "请注意，此信息来自课程目录的保存副本，并非实时查询。关于先决条件的具体逻辑（例如是全部需要还是任选其一）"
    "未在记录中明确说明。"
)
# The same answer in the wording 4.6 asks for. 中文：同一条回答，用 4.6 要求的说法。
ASKED_FOR = (
    "CS 6140 介绍机器学习和数据挖掘的多种技术，包括监督学习、无监督学习和强化学习，并有一个编程项目。\n\n"
    f"根据 [NEU 官方课程目录]({CS})，记录列出的先修课有 CS 5800、CS 7800，但没有说明是都要修还是任选其一，"
    "选课前请向学校确认。以上来自目录的存档副本，不是实时核对。"
)


def case(*, year_rule: bool = False):
    """(prompt, course block, AnswerContext) for CS 6140 as the fixture's catalog page has it; without a year rule, as
    on the live card, or with the fixture's own clause as one. 中文：按夹具的目录页构造 CS 6140；默认没有年度规则（和线上
    卡片一样），year_rule 时用夹具自己的条款当年度规则。"""
    entries = _parse_dept_html(FIXTURE.read_text(encoding="utf-8"), source_url=CS)
    entry = next(item for item in entries if item.course_code == "CS 6140")
    course = Course(course_id="neu-cs-6140", primary_code="CS 6140", primary_name="Machine Learning", credits=4,
                    prereqs=list(entry.prereqs))
    clause = entry.requisites.prerequisite
    editions = [RequisiteEdition(
        catalog_year="2025-2026", catalog_url=CS, captured_at=datetime(2026, 5, 3, tzinfo=timezone.utc),
        prerequisite=RequisiteSectionEvidence(status=clause.status, rule=clause.rule, clause_text=clause.raw_text),
        corequisite=RequisiteSectionEvidence(status="not_listed"))] if year_rule else []
    evidence = course_answer_evidence(course, CatalogSourceRepository.snapshot(entry),
                                      requisites=RequisiteEvidence(storage="available", editions=editions))
    hits = [SearchHit(course=course, score=1.0)]
    block = format_courses_block(hits, {course.course_id: evidence})
    context = context_from_records(block, [evidence.model_dump(mode="json")], lang="zh")
    return build_prompt(QUERY, hits, evidence={course.course_id: evidence}, retrieval_mode="alias"), block, context


def test_the_model_gets_the_codes_under_a_name_that_says_their_and_or_is_unknown():
    prompt, block, context = case()
    record = json.loads(block)[0]
    assert record["recorded_metadata"][FLAT_PREREQS_KEY] == ["CS 5800", "CS 7800"]
    assert record["answer_evidence"]["catalog"][FLAT_PREREQS_KEY] == ["CS 5800", "CS 7800"]
    assert "prerequisite_logic_unavailable" in record["answer_evidence"]["warnings"]
    assert record["catalog_requisites"] == {"editions": [], "editions_not_shown": 0}
    # Nothing the model reads about this course says "or": the catalog's own OR never reached the snapshot.
    assert not re.search(r"\bor\b|或", block)
    assert block in prompt and context.flat_prereqs == (("CS 6140", ("CS 5800", "CS 7800")),)


def test_the_live_answer_is_flagged_where_it_states_the_or():
    _, _, context = case()
    checks = check_answer(LIVE_ANSWER, context)
    assert checks["prereq_relation_asserted"] == [{
        "course": "CS 6140", "codes": ["CS 5800", "CS 7800"], "kinds": ["or"],
        "sentence": f"根据 [NEU 官方课程目录]({CS})，该课程的先决条件是 CS 5800 或 CS 7800。"}]
    # Its caveat is there, only too late: the caveat check counts it (it did not before checker 2.7).
    assert "prereq_logic" not in checks["caveats_missing"]
    assert not any(checks[name] for name in HARD_FAILURES)


def test_the_wording_the_prompt_asks_for_passes():
    _, _, context = case()
    checks = check_answer(ASKED_FOR, context)
    assert checks["prereq_relation_asserted"] == [] and checks["caveats_missing"] == []
    assert not any(checks[name] for name in HARD_FAILURES)


def test_with_a_year_rule_the_or_is_the_records_own():
    prompt, block, context = case(year_rule=True)
    record = json.loads(block)[0]
    assert FLAT_PREREQS_KEY not in block and '"any_of": [' in block
    assert "prerequisite_logic_unavailable" not in record["answer_evidence"]["warnings"]
    assert context.flat_prereqs == () and not context.prereq_relevant
    assert check_answer(LIVE_ANSWER, context)["prereq_relation_asserted"] == []
