"""Ask the real model the way /chat does and check the answers (eval/answer_checks.py).

Evidence comes only from the live API's GET /course/{id} (read-only, and tagged with X-Eval-Run so
it is never mistaken for a student). Prompts come from the local llm/prompts/chat_v4.py, built like
api/routes/chat.py builds them. Answers come from llm.gemini_client.generate_text_stream with the
defaults /chat uses. Writes results.json, one Markdown file per answer, and summary.md to --out.
Never prints the API key.

Run from the repo root in the project venv (config.settings reads GEMINI_API_KEY from .env):
    python scripts/eval_answers_live.py --api-base http://<api-host>:8000 --out /tmp/answer-eval
    python scripts/eval_answers_live.py --api-base http://<api-host>:8000 --out /tmp/x --dry-run
    python scripts/eval_answers_live.py --rescore /tmp/answer-eval/results.json --out /tmp/answer-recheck
Exit code: 0 every planned answer was checked and none failed a hard check (or a dry run), 1 some
answer failed a hard check, 2 setup, argument or input error (an unreachable API or a non-200 GET,
a missing or malformed --questions or --rescore file, a payload that does not fit, an --out folder
that cannot be created or written), 3 incomplete (a model call failed, the call cap stopped the run
early, or no answer was checked). Every prompt and context is built and saved before the first
model call. --rescore keeps the original run's errors and requires a new --out directory; originals stay unchanged.

中文：按 /chat 的方式问真实模型，并检查回答（eval/answer_checks.py）。证据只来自线上 API 的
GET /course/{id}（只读，并带 X-Eval-Run 标记，不会被当成学生查询）；提示词用本地的
llm/prompts/chat_v4.py，构造方式与 api/routes/chat.py 相同；回答来自
llm.gemini_client.generate_text_stream，参数与 /chat 一样。结果写到 --out：results.json、每个
回答一个 Markdown 文件、summary.md。不会打印 API key。退出码：0 计划的每个回答都检查过且没有硬失败
（或空跑），1 有回答没过硬检查，2 准备阶段、参数或输入出错（API 连不上或 GET 不是 200、--questions
或 --rescore 文件缺失或格式不对、数据对不上、--out 目录建不了或写不进），3 不完整（有模型调用失败、
调用上限提前停止，或没有任何回答可检查）。第一次调用模型之前会先构造并保存好全部提示词和上下文。
--rescore 保留原来那次运行的错误，必须给 --out 新目录，原文件永不覆盖。
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import subprocess
import sys
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# The questions of the 2026-10-05 live checks: zh/en, alias/hybrid, one with the program notice.
# 中文：2026-10-05 真实模型复核用的问题：中英文、alias/hybrid、一个带培养方案提示。
DEFAULT_QUESTIONS = [
    {"qid": "Q1", "lang": "zh", "query": "CS 5800 难不难？每周大概要花多少时间？",
     "course_ids": ["neu-cs-5800"], "route": "alias", "notices": []},
    {"qid": "Q2", "lang": "en", "query": "How heavy is the workload in CS 5200? Roughly how many hours a week should I plan for?",
     "course_ids": ["neu-cs-5200"], "route": "alias", "notices": []},
    {"qid": "Q3", "lang": "zh", "query": "CS 5800 和 CS 5200 哪门课更难、作业更多？",
     "course_ids": ["neu-cs-5800", "neu-cs-5200"], "route": "alias", "notices": []},
    {"qid": "Q4", "lang": "en", "query": "What are the prerequisites for CS 6140? Do I need to have taken all of them before I can enroll?",
     "course_ids": ["neu-cs-6140"], "route": "alias", "notices": []},
    {"qid": "Q5", "lang": "zh", "query": "我刚进 MS CS 项目，第一学期应该选哪些课？",
     "course_ids": ["neu-cs-5010", "neu-cs-5800", "neu-cs-5200"], "route": "hybrid",
     "notices": ["program_schedule_unverified"]},
]


def fetch_courses(client, course_ids: Iterable[str]) -> dict[str, dict]:
    """GET /course/{id} for each id; the client carries base_url and the X-Eval-Run header."""
    payloads = {}
    for course_id in dict.fromkeys(course_ids):
        response = client.get(f"/course/{course_id}")
        if response.status_code != 200:
            raise RuntimeError(f"GET /course/{course_id} returned {response.status_code}")
        payloads[course_id] = response.json()
    return payloads


def course_parts(payload: dict):
    from pydantic import ValidationError  # noqa: PLC0415

    from schemas.answer_evidence import CatalogSnapshot, RequisiteEvidence  # noqa: PLC0415
    from schemas.course import Course  # noqa: PLC0415

    course = Course.model_validate({key: payload[key] for key in Course.model_fields if key in payload})
    evidence = payload.get("answer_evidence") or {}
    try:
        catalog = CatalogSnapshot.model_validate(evidence["catalog"]) if evidence.get("catalog") else None
    except ValidationError:
        catalog = None  # The prompt then gets no snapshot, as /chat would.
    # The detail API builds the same year rules as /chat (4.4); an older API sends none.
    # 中文：详情接口给出的年度规则和 /chat 相同（4.4）；旧接口没有这一项。
    try:
        requisites = RequisiteEvidence.model_validate(evidence["requisites"]) if evidence.get("requisites") else None
    except ValidationError:
        requisites = None
    return course, catalog, requisites


def course_records(courses_block: str) -> list[dict]:
    """The prompt's JSON course block, or its explicit no-match sentinel.
    中文：只接受课程 JSON 列表或明确的无结果标记。"""
    if courses_block.strip() == "(no matches found in catalog)":
        return []
    records = json.loads(courses_block)
    if not isinstance(records, list):
        raise ValueError("course block must be a list")
    return records


def unstated_values(courses_block: str) -> tuple[tuple[str, str, float], ...]:
    """Unstated numeric estimates, retaining their course and field identity.
    中文：未被同一课程、同一字段引文直接陈述的值，保留三元组身份。"""
    from eval.answer_checks import NUMERIC_FIELDS, number_pattern  # noqa: PLC0415

    values = set()
    for record in course_records(courses_block):
        quotes = record["answer_evidence"]["field_evidence"]
        candidates = [(item["field"], item["supported_value"]) for item in quotes]
        metadata = record["recorded_metadata"]
        candidates += [(name, metadata.get(name)) for name in NUMERIC_FIELDS]
        for name, value in candidates:
            if name in NUMERIC_FIELDS and isinstance(value, (int, float)) and not isinstance(value, bool):
                if not any(number_pattern(value).search(item["quote"]) for item in quotes if item["field"] == name):
                    values.add((record["primary_code"], name, float(value)))
    return tuple(sorted(values))


def _keys(node, found: set[str]) -> set[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            found.add(key)
            _keys(value, found)
    elif isinstance(node, list):
        for value in node:
            _keys(value, found)
    return found


def conflict_values(records: list[dict]) -> tuple:
    """Numeric disagreements visible in the prompt, not a claim that either source is correct.
    中文：只记提示词里可见的数值分歧，不裁定哪一来源正确。"""
    conflicts = []
    for record in records:
        evidence, metadata = record["answer_evidence"], record["recorded_metadata"]
        catalog = evidence.get("catalog") or {}
        pairs = {"credits": [metadata.get("credits"), catalog.get("credits")]}
        for item in evidence["field_evidence"]:
            patterns = ((r"每周\s*(\d+(?:\.\d+)?)\s*(?:小时|hours?\b|hrs?\b)",
                         r"(\d+(?:\.\d+)?)\s*(?:hours?\b|hrs?\b|小时)\s*(?:(?:a|per|each)\s+week\b|weekly\b|/\s*(?:week\b|wk\b|周))")
                        if item["field"] == "workload_hours_per_week" else
                        (r"(?:difficulty|难度)\D{0,12}(\d+(?:\.\d+)?)",) if item["field"] == "difficulty_score" else ())
            if patterns:
                pairs.setdefault(item["field"], [metadata.get(item["field"])]).append(item["supported_value"])
                pairs[item["field"]].extend(
                    float(match[1]) for pattern in patterns for match in re.finditer(pattern, item["quote"], re.I))
        for name, candidates in pairs.items():
            values = tuple(sorted({float(value) for value in candidates if type(value) in (int, float)}))
            if len(values) > 1:
                conflicts.append((record["primary_code"], name, values))
    return tuple(conflicts)


def context_from_records(block: str, evidence: list[dict], *, lang: str, notices=()):
    """Shared fixed-evidence/actual-route context projection; no API/model work.
    中文：固定证据与实际路由共用上下文投影，不请求 API 或模型。"""
    from eval.answer_checks import AnswerContext  # noqa: PLC0415

    records = course_records(block)
    catalogs = [item.get("catalog") for item in evidence]
    urls = {catalog["catalog_url"] for catalog in catalogs if catalog is not None}
    urls.update(edition["catalog_url"] for item in evidence for edition in (item.get("requisites") or {}).get("editions", []))
    unstated = unstated_values(block)
    return AnswerContext(
        lang=lang, allowed_urls=frozenset(urls),
        has_rmp_data=any(source.startswith("rmp_review_") for item in evidence for source in item["source_review_ids"])
        or any(quote["source_id"].startswith("rmp_review_") for item in evidence for quote in item["field_evidence"]),
        fetch_date_relevant=any(catalog is not None and catalog["retrieved_at"] is None for catalog in catalogs),
        no_catalog_relevant=any(catalog is None for catalog in catalogs),
        prereq_relevant=any("prerequisite_logic_unavailable" in item["warnings"] for item in evidence),
        program_notice="program_schedule_unverified" in notices,
        unstated_values=tuple(sorted({value for _, _, value in unstated})),
        course_codes=tuple(record["primary_code"] for record in records), unstated=unstated,
        conflicts=conflict_values(records), prompt_keys=frozenset(_keys(records, set())),
    )


def checker_identity() -> dict:
    from eval.answer_checks import CHECKER_VERSION  # noqa: PLC0415

    return {"checker_version": CHECKER_VERSION,
            "answer_checks_sha256": hashlib.sha256((PROJECT_ROOT / "eval/answer_checks.py").read_bytes()).hexdigest()}


def code_identity() -> dict:
    files = ("api/routes/chat.py", "api/routes/common.py", "api/routes/search.py", "llm/prompts/chat_v4.py",
             "llm/prompts/chat_v3.py", "rag/answer_evidence.py", "eval/answer_checks.py",
             "scripts/eval_answers_live.py", "db/init.sql", "app/chat_view.py", "app/state_manager.py",
             "app/streamlit_app.py", "rag/hybrid.py", "rag/reranker.py", "rag/retriever.py", "api/dependencies.py",
             "config/settings.py", "rag/acronyms.py", "rag/hyde.py", "rag/index.py", "api/main.py",
             "app/api_client.py", "db/connection.py", "rag/embedder.py", "rag/onnx_backend.py", "rag/openvino_backend.py")
    try:
        result = subprocess.run(["git", "-C", str(PROJECT_ROOT), "rev-parse", "HEAD"],
                                capture_output=True, text=True, timeout=5, check=True)
        commit = result.stdout.strip()
        dirty = bool(subprocess.run(["git", "-C", str(PROJECT_ROOT), "status", "--porcelain"],
                                   capture_output=True, text=True, timeout=5, check=True).stdout.strip())
    except (OSError, RuntimeError, subprocess.SubprocessError):
        commit = None
        dirty = None
    return {"git_commit": commit, "git_dirty": dirty, "code_files_sha256": {
        name: hashlib.sha256((PROJECT_ROOT / name).read_bytes()).hexdigest() for name in files}}


def build_case(question: dict, payloads: dict[str, dict]):
    """(prompt, AnswerContext) for one question, mirroring api/routes/chat.py."""
    from llm.prompts.chat_v4 import build_prompt, format_courses_block  # noqa: PLC0415
    from rag.answer_evidence import course_answer_evidence  # noqa: PLC0415
    from rag.retriever import SearchHit  # noqa: PLC0415

    parts = {course_id: course_parts(payloads[course_id]) for course_id in question["course_ids"]}
    hits = [SearchHit(course=course, score=1.0) for course, _, _ in parts.values()]
    evidence = {course.course_id: course_answer_evidence(course, catalog, program_seed=question["route"] == "program",
                                                         requisites=requisites)
                for course, catalog, requisites in parts.values()}
    prompt = build_prompt(question["query"], hits, history=None, evidence=evidence,
                          retrieval_mode=question["route"], notices=question["notices"])
    block = format_courses_block(hits, evidence)
    context = context_from_records(block, [item.model_dump(mode="json") for item in evidence.values()],
                                   lang=question["lang"], notices=question["notices"])
    return prompt, context


def context_to_json(context) -> dict:
    from dataclasses import asdict  # noqa: PLC0415

    return {key: sorted(value) if isinstance(value, frozenset) else list(value) if isinstance(value, tuple) else value
            for key, value in asdict(context).items()}


def context_from_json(data: dict):
    from eval.answer_checks import AnswerContext  # noqa: PLC0415

    values = {**data, "allowed_urls": frozenset(data["allowed_urls"]), "prompt_keys": frozenset(data["prompt_keys"]),
              "unstated_values": tuple(data["unstated_values"])}
    for name in ("course_codes", "unstated", "conflicts"):
        if name in values:
            values[name] = (None if name == "course_codes" and values[name] is None else
                            tuple(values[name]) if name == "course_codes" else
                            tuple(tuple(item) if name == "unstated" else (item[0], item[1], tuple(item[2]))
                                  for item in values[name]))
    return AnswerContext(**values)


def run_status(report: dict) -> str:
    """'dry run', 'complete' (every planned call returned an answer that was checked) or
    'incomplete' (a call failed, the call cap stopped the run early, or nothing was checked).
    A report written before planned_calls existed counts its model calls as the plan.
    中文：'dry run'、'complete'（计划的每次调用都有回答且检查过）或 'incomplete'（有调用失败、
    调用上限提前停止，或没有回答可检查）。没有 planned_calls 的旧报告把实际调用次数当作计划。"""
    if report.get("dry_run", report["model_calls"] == 0 and not report["records"]):
        return "dry run"
    answered = sum(1 for record in report["records"] if "checks" in record)
    return "complete" if 0 < answered == report.get("planned_calls", report["model_calls"]) else "incomplete"


def exit_code(report: dict) -> int:
    """0 complete (or a dry run) with no hard failure, 1 some answer failed a hard check,
    3 incomplete. 中文：0 完整（或空跑）且没有硬失败，1 有回答没过硬检查，3 不完整。"""
    from eval.answer_checks import HARD_FAILURES  # noqa: PLC0415

    if any(report["summary"][name] for name in HARD_FAILURES):
        return 1
    return 3 if report["status"] == "incomplete" else 0


def write_report(out: Path, report: dict) -> None:
    """results.json and summary.md from a report dict (shared by run and rescore)."""
    from eval.answer_checks import HARD_FAILURES, summarize  # noqa: PLC0415

    report["summary"] = summarize([record["checks"] for record in report["records"] if "checks" in record])
    report["status"] = run_status(report)
    (out / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    planned = report.get("planned_calls", report["model_calls"])
    lines = [f"# Answer check · prompt {report['prompt_version']} · {report['status']}", "",
             f"chat_v4.py {report['chat_v4_sha256'][:12]} · {planned} planned · {report['model_calls']} model calls · "
             f"{report['errors']} errors · {report['summary']['answers']} answers checked", "",
             "| answer | hard failures | caveats missing | as reviewer-reported | unattributed | saved-copy sentences |",
             "|---|---|---|---|---|---|"]
    for record in report["records"]:
        if "checks" not in record:
            lines.append(f"| {record['qid']} run {record['run']} | error | | | | |")
            continue
        checks = record["checks"]
        failed = ", ".join(name for name in HARD_FAILURES if checks[name]) or "none"
        lines.append(f"| {record['qid']} run {record['run']} | {failed} | {', '.join(checks['caveats_missing']) or '—'} | "
                     f"{len(checks['estimates_as_reported'])} | "
                     f"{sum(item['kind'] == 'unattributed' for item in checks['estimates'])} | {checks['saved_copy_mentions']} |")
    lines += ["", "```json", json.dumps(report["summary"], ensure_ascii=False, indent=2), "```", ""]
    (out / "summary.md").write_text("\n".join(lines), encoding="utf-8")


REPORT_TYPES = {"prompt_version": str, "chat_v4_sha256": str, "model_calls": int, "errors": int, "records": list}
OPTIONAL_REPORT_TYPES = {"planned_calls": int, "dry_run": bool}
CONTEXT_KEYS = ("lang", "allowed_urls", "prompt_keys", "unstated_values")
CONTEXT_FLAGS = ("has_rmp_data", "fetch_date_relevant", "no_catalog_relevant", "prereq_relevant", "program_notice")


def _is(value: object, kind: type) -> bool:
    return isinstance(value, kind) and not (kind is int and isinstance(value, bool))


def _context_ok(context: object) -> bool:
    """A saved AnswerContext as context_to_json writes it. 中文：context_to_json 写出的上下文形状。"""
    from dataclasses import fields  # noqa: PLC0415

    from eval.answer_checks import AnswerContext  # noqa: PLC0415

    if not isinstance(context, dict) or not set(CONTEXT_KEYS) <= set(context) <= {item.name for item in fields(AnswerContext)}:
        return False
    numeric = lambda value: type(value) in (int, float) and math.isfinite(value)
    return (context["lang"] in ("zh", "en")
            and all(_is(context[name], list) and all(_is(item, str) for item in context[name])
                    for name in ("allowed_urls", "prompt_keys"))
            and _is(context["unstated_values"], list)
            and all(numeric(value) for value in context["unstated_values"])
            and (context.get("course_codes") is None or isinstance(context["course_codes"], list)
                 and all(isinstance(code, str) and bool(code.strip()) for code in context["course_codes"]))
            and all(name not in context or isinstance(context[name], list) and all(
                isinstance(item, list) and len(item) == 3 and isinstance(item[0], str)
                and item[1] in (("workload_hours_per_week", "difficulty_score") if name == "unstated"
                                else ("credits", "workload_hours_per_week", "difficulty_score"))
                and (numeric(item[2]) if name == "unstated" else isinstance(item[2], list) and all(map(numeric, item[2])))
                for item in context[name]) for name in ("unstated", "conflicts"))
            and all(_is(context[flag], bool) for flag in CONTEXT_FLAGS if flag in context))


def load_report(results: Path) -> dict:
    """A saved results.json, checked for the shape and types rescoring needs, so a bad file is a
    setup error (exit 2) while a bug in the checks themselves keeps its traceback. 中文：读取保存的
    results.json 并检查重评需要的形状和类型：文件不对是准备阶段的错误（退出码 2），检查本身的错误仍
    保留 traceback。"""
    report = json.loads(results.read_text(encoding="utf-8"))
    if not isinstance(report, dict) or not all(_is(report.get(key), kind) for key, kind in REPORT_TYPES.items()) or not all(
            _is(report[key], kind) for key, kind in OPTIONAL_REPORT_TYPES.items() if key in report):
        raise ValueError(f"not a results.json: it needs {', '.join(REPORT_TYPES)} with their types")
    for index, record in enumerate(report["records"]):
        if not isinstance(record, dict) or not _is(record.get("qid"), str) or not _is(record.get("run"), int):
            raise ValueError(f"record {index} needs a text qid and a numeric run")
        if "answer" in record:
            if not _is(record["answer"], str) or not _context_ok(record.get("context")):
                raise ValueError(f"record {index}: an answer needs to be text, with its saved context")
        elif "checks" in record:
            raise ValueError(f"record {index} has checks but no answer to recheck")
    return report


def rescore(results: Path, report: dict | None = None, *, out: Path) -> dict:
    """Re-run the current checks on saved answers (no API or model calls), e.g. after tuning a
    detector. 中文：用当前的检查重新评一遍已保存的回答（不调 API、不调模型），比如调整检测规则之后。"""
    from eval.answer_checks import check_answer  # noqa: PLC0415

    report = copy.deepcopy(load_report(results) if report is None else report)
    report["rescore_of"] = {"path": str(results), "sha256": hashlib.sha256(results.read_bytes()).hexdigest(),
                            "checker_version_before": report.get("checker_version")}
    report.update(checker_identity())
    report["checker_version_after"] = report["checker_version"]
    report.setdefault("evidence_layer", "legacy_unknown")
    for record in report["records"]:
        if "answer" in record:
            record["checks"] = check_answer(record["answer"], context_from_json(record["context"]))
    report["rescored_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out.mkdir(parents=True, exist_ok=False)
    write_report(out, report)
    return report


QUESTION_KEYS = ("qid", "lang", "query", "course_ids", "route", "notices")
# A qid names the output files (prompts/<qid>.txt, answers/<qid>_run<n>.md).
# 中文：qid 用作输出文件名（prompts/<qid>.txt、answers/<qid>_run<n>.md）。
QID = re.compile(r"[A-Za-z0-9_-]{1,64}")


def validate_questions(questions: object) -> list[dict]:
    """A --questions file must be a non-empty list of questions shaped like DEFAULT_QUESTIONS; a bad
    one is a setup error, found before any request. 中文：--questions 文件必须是非空列表，每个问题
    的形状和 DEFAULT_QUESTIONS 一样；不合格是准备阶段的错误，在发任何请求之前就发现。"""
    if not isinstance(questions, list) or not questions:
        raise ValueError("the questions file must hold a non-empty JSON list")
    seen: set[str] = set()
    for index, question in enumerate(questions):
        if not isinstance(question, dict) or any(key not in question for key in QUESTION_KEYS):
            raise ValueError(f"question {index} needs the keys {', '.join(QUESTION_KEYS)}")
        qid = question["qid"]
        # Unique ignoring case too: on a case-insensitive file system (Windows, /mnt in WSL, macOS)
        # "Q1" and "q1" would write the same files. 中文：不分大小写也要唯一：在不分大小写的文件系统上
        # （Windows、WSL 的 /mnt、macOS），"Q1" 和 "q1" 会写到同一些文件。
        if not isinstance(qid, str) or not QID.fullmatch(qid) or qid.casefold() in seen:
            raise ValueError(f"question {index}: qid must be unique, 1-64 letters, digits, _ or - (it names files)")
        seen.add(qid.casefold())
        if question["lang"] not in ("zh", "en") or question["route"] not in ("alias", "hybrid", "program"):
            raise ValueError(f"question {index}: lang must be zh or en, route alias, hybrid or program")
        ids = question["course_ids"]
        if not isinstance(ids, list) or not ids or not all(isinstance(cid, str) and cid for cid in ids):
            raise ValueError(f"question {index}: course_ids must be a non-empty list of course IDs")
        if not isinstance(question["notices"], list):
            raise ValueError(f"question {index}: notices must be a list")
    return questions


def prepare(questions: list[dict], payloads: dict[str, dict]) -> list[tuple[dict, str, object]]:
    """(question, prompt, context) for every question, built before the first model call, so a bad
    question or payload stops the run before it costs anything. 中文：在第一次调用模型之前先为每个
    问题构造（问题，提示词，上下文），坏的问题或数据在花钱之前就让运行停下。"""
    return [(question, *build_case(question, payloads)) for question in questions]


def save_prompts(out: Path, cases: list[tuple[dict, str, object]]) -> None:
    """Create the output folders and write every prompt and context, before the first model call.
    中文：建好输出目录并写出全部提示词和上下文，在第一次调用模型之前。"""
    for name in ("answers", "prompts"):
        (out / name).mkdir(parents=True, exist_ok=True)
    for question, prompt, context in cases:
        (out / "prompts" / f"{question['qid']}.txt").write_text(prompt, encoding="utf-8")
        (out / "prompts" / f"{question['qid']}.context.json").write_text(
            json.dumps(context_to_json(context), ensure_ascii=False, indent=2), encoding="utf-8")


def redact(message: str, secret: str | None) -> str:
    if secret:
        message = message.replace(secret, "[REDACTED]")
    return re.sub(r"AIza[0-9A-Za-z_\-]{20,}", "[REDACTED]", message)


def run(questions: list[dict], payloads: dict[str, dict], *, out: Path, runs: int, max_calls: int,
        stream_fn: Callable[[str], Iterable[str]] | None, secret: str | None = None) -> dict:
    """Ask each question `runs` times (stream_fn None = dry run: prompts only) and check every answer."""
    from eval.answer_checks import check_answer  # noqa: PLC0415
    from llm.prompts.chat_v4 import PROMPT_VERSION  # noqa: PLC0415

    cases = prepare(questions, payloads)
    save_prompts(out, cases)
    records, calls = [], 0
    for question, prompt, context in cases:
        for attempt in range(1, runs + 1 if stream_fn else 1):
            if calls >= max_calls:
                break
            calls += 1
            record = {"qid": question["qid"], "run": attempt, "lang": question["lang"], "query": question["query"],
                      "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                      "context": context_to_json(context)}
            try:
                answer = "".join(stream_fn(prompt))
            except Exception as exc:  # noqa: BLE001 - recorded, never raised with the key in it
                record["error"] = redact(f"{type(exc).__name__}: {exc}", secret)[:500]
                records.append(record)
                continue
            record["answer"] = answer
            record["checks"] = check_answer(answer, context)
            name = f"{question['qid']}_run{attempt}.md"
            (out / "answers" / name).write_text(f"<!-- {question['query']} -->\n\n{answer}\n", encoding="utf-8")
            records.append(record)
    chat_v4 = PROJECT_ROOT / "llm/prompts/chat_v4.py"
    report = {
        **checker_identity(), **code_identity(),
        "evidence_layer": "live_model" if stream_fn else "live_api",
        "prompt_version": PROMPT_VERSION,
        "chat_v4_sha256": hashlib.sha256(chat_v4.read_bytes()).hexdigest(),
        "started_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dry_run": stream_fn is None,
        "planned_calls": len(questions) * runs if stream_fn else 0,
        "model_calls": calls if stream_fn else 0,
        "errors": sum(1 for record in records if "error" in record),
        "records": records,
    }
    write_report(out, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--api-base", help="live API base URL (GET /course only)")
    parser.add_argument("--out", type=Path, help="output directory (created)")
    parser.add_argument("--rescore", type=Path, metavar="RESULTS_JSON",
                        help="re-check the answers saved in a previous results.json; no API or model calls")
    parser.add_argument("--eval-run", default=f"answer-eval-{datetime.now(timezone.utc):%Y%m%d}",
                        help="X-Eval-Run tag for the GET requests")
    parser.add_argument("--questions", type=Path, help="JSON list of questions (default: the built-in five)")
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--max-calls", type=int, default=25)
    parser.add_argument("--dry-run", action="store_true",
                        help="build and save the prompts and contexts, no model calls")
    args = parser.parse_args(argv)
    if args.runs < 1 or args.max_calls < 1:
        parser.error("--runs and --max-calls must be at least 1")
    # A missing or malformed input file, or a payload that does not fit, is a setup error (2), not
    # a hard failure (1). 中文：输入文件缺失或格式不对、数据对不上，都是准备阶段的错误（2），不是硬失败（1）。
    setup_errors = (OSError, ValueError, KeyError, TypeError)
    if args.rescore:
        try:
            saved = load_report(args.rescore)
            if args.out is None:
                raise ValueError("--rescore requires --out with a new directory")
            if args.out.exists():
                raise FileExistsError("--out must be a new directory")
        except setup_errors as exc:
            print(f"setup error: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
        try:
            report = rescore(args.rescore, saved, out=args.out)
        except OSError as exc:
            print(f"setup error: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
        print(json.dumps({"rescored": str(args.rescore), "status": report["status"], "summary": report["summary"]},
                         ensure_ascii=False))
        return exit_code(report)
    if not args.api_base or not args.out:
        parser.error("--api-base and --out are required unless --rescore is given")

    import httpx  # noqa: PLC0415

    headers = {"X-Eval-Run": args.eval_run, "User-Agent": "neu-compass-answer-eval/1"}
    try:
        questions = (validate_questions(json.loads(args.questions.read_text(encoding="utf-8"))) if args.questions
                     else DEFAULT_QUESTIONS)
        with httpx.Client(base_url=args.api_base.rstrip("/"), headers=headers, timeout=30.0) as client:
            payloads = fetch_courses(client, (cid for question in questions for cid in question["course_ids"]))
        # Every prompt and context is built and saved (folders created) before the first model call.
        save_prompts(args.out, prepare(questions, payloads))
    except (*setup_errors, RuntimeError, httpx.HTTPError) as exc:
        print(f"setup error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    stream_fn, secret = None, None
    if not args.dry_run:
        from config import settings  # noqa: PLC0415
        from llm.gemini_client import generate_text_stream  # noqa: PLC0415

        stream_fn, secret = generate_text_stream, settings.gemini_api_key
    report = run(questions, payloads, out=args.out, runs=args.runs, max_calls=args.max_calls,
                 stream_fn=stream_fn, secret=secret)
    print(json.dumps({"prompt_version": report["prompt_version"], "status": report["status"],
                      "planned_calls": report["planned_calls"], "model_calls": report["model_calls"],
                      "errors": report["errors"], "summary": report["summary"]}, ensure_ascii=False))
    print(f"report: {args.out / 'summary.md'}")
    return exit_code(report)


if __name__ == "__main__":
    sys.exit(main())
