"""Ask the real model the way /chat does and check the answers (eval/answer_checks.py).

Evidence comes only from the live API's GET /course/{id} (read-only, and tagged with X-Eval-Run so
it is never mistaken for a student). Prompts come from the local llm/prompts/chat_v4.py, built like
api/routes/chat.py builds them. Answers come from llm.gemini_client.generate_text_stream with the
defaults /chat uses. Writes results.json, one Markdown file per answer, and summary.md to --out.
Never prints the API key.

Run from the repo root in the project venv (config.settings reads GEMINI_API_KEY from .env):
    python scripts/eval_answers_live.py --api-base http://<api-host>:8000 --out /tmp/answer-eval
    python scripts/eval_answers_live.py --api-base http://<api-host>:8000 --out /tmp/x --dry-run
    python scripts/eval_answers_live.py --rescore /tmp/answer-eval/results.json   # after tuning checks
Exit code: 0 every planned answer was checked and none failed a hard check (or a dry run), 1 some
answer failed a hard check, 2 setup or argument error, 3 incomplete (a model call failed, the call
cap stopped the run early, or no answer was checked). --rescore keeps the original run's errors.

中文：按 /chat 的方式问真实模型，并检查回答（eval/answer_checks.py）。证据只来自线上 API 的
GET /course/{id}（只读，并带 X-Eval-Run 标记，不会被当成学生查询）；提示词用本地的
llm/prompts/chat_v4.py，构造方式与 api/routes/chat.py 相同；回答来自
llm.gemini_client.generate_text_stream，参数与 /chat 一样。结果写到 --out：results.json、每个
回答一个 Markdown 文件、summary.md。不会打印 API key。退出码：0 计划的每个回答都检查过且没有硬失败
（或空跑），1 有回答没过硬检查，2 准备阶段或参数出错，3 不完整（有模型调用失败、调用上限提前停止，
或没有任何回答可检查）。--rescore 保留原来那次运行的错误。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
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

    from schemas.answer_evidence import CatalogSnapshot  # noqa: PLC0415
    from schemas.course import Course  # noqa: PLC0415

    course = Course.model_validate({key: payload[key] for key in Course.model_fields if key in payload})
    raw = (payload.get("answer_evidence") or {}).get("catalog")
    try:
        catalog = CatalogSnapshot.model_validate(raw) if raw else None
    except ValidationError:
        catalog = None  # The prompt then gets no snapshot, as /chat would.
    return course, catalog


def unstated_values(courses_block: str) -> tuple[float, ...]:
    """Numeric estimates in the prompt that no supplied quote states (supported values and the
    recorded workload/difficulty), so an answer giving them must call them estimates."""
    from eval.answer_checks import number_pattern  # noqa: PLC0415

    values = set()
    for record in json.loads(courses_block):
        quotes = record["answer_evidence"]["field_evidence"]
        candidates = [(item["field"], item["supported_value"]) for item in quotes]
        metadata = record["recorded_metadata"]
        candidates += [(name, metadata.get(name)) for name in ("workload_hours_per_week", "difficulty_score")]
        for name, value in candidates:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if not any(number_pattern(value).search(item["quote"]) for item in quotes if item["field"] == name):
                    values.add(float(value))
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


def build_case(question: dict, payloads: dict[str, dict]):
    """(prompt, AnswerContext) for one question, mirroring api/routes/chat.py."""
    from eval.answer_checks import AnswerContext  # noqa: PLC0415
    from llm.prompts.chat_v4 import build_prompt, format_courses_block  # noqa: PLC0415
    from rag.answer_evidence import course_answer_evidence  # noqa: PLC0415
    from rag.retriever import SearchHit  # noqa: PLC0415

    parts = {course_id: course_parts(payloads[course_id]) for course_id in question["course_ids"]}
    hits = [SearchHit(course=course, score=1.0) for course, _ in parts.values()]
    evidence = {course.course_id: course_answer_evidence(course, catalog, program_seed=question["route"] == "program")
                for course, catalog in parts.values()}
    prompt = build_prompt(question["query"], hits, history=None, evidence=evidence,
                          retrieval_mode=question["route"], notices=question["notices"])
    block = format_courses_block(hits, evidence)
    catalogs = [catalog for _, catalog in parts.values()]
    context = AnswerContext(
        lang=question["lang"],
        allowed_urls=frozenset(catalog.catalog_url for catalog in catalogs if catalog is not None),
        has_rmp_data=any(any(source.startswith("rmp_review_") for source in course.source_review_ids)
                         or any(item.source_id.startswith("rmp_review_") for item in course.evidence_snippets)
                         for course, _ in parts.values()),
        fetch_date_relevant=any(catalog is not None and catalog.retrieved_at is None for catalog in catalogs),
        no_catalog_relevant=any(catalog is None for catalog in catalogs),
        prereq_relevant=any(course.prereqs for course, _ in parts.values())
        or any(catalog is not None and catalog.prereq_codes for catalog in catalogs),
        program_notice="program_schedule_unverified" in question["notices"],
        unstated_values=unstated_values(block),
        prompt_keys=frozenset(_keys(json.loads(block), set())),
    )
    return prompt, context


def context_to_json(context) -> dict:
    from dataclasses import asdict  # noqa: PLC0415

    return {key: sorted(value) if isinstance(value, frozenset) else list(value) if isinstance(value, tuple) else value
            for key, value in asdict(context).items()}


def context_from_json(data: dict):
    from eval.answer_checks import AnswerContext  # noqa: PLC0415

    return AnswerContext(**{**data, "allowed_urls": frozenset(data["allowed_urls"]),
                            "prompt_keys": frozenset(data["prompt_keys"]),
                            "unstated_values": tuple(data["unstated_values"])})


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
    lines = [f"# Answer check · prompt {report['prompt_version']}", "", f"**{report['status']}** · "
             f"chat_v4.py {report['chat_v4_sha256'][:12]} · {planned} planned · {report['model_calls']} model calls · "
             f"{report['errors']} errors · {report['summary']['answers']} answers checked", "",
             "| answer | hard failures | caveats missing | as reviewer-reported | saved-copy sentences |",
             "|---|---|---|---|---|"]
    for record in report["records"]:
        if "checks" not in record:
            lines.append(f"| {record['qid']} run {record['run']} | error | | | |")
            continue
        checks = record["checks"]
        failed = ", ".join(name for name in HARD_FAILURES if checks[name]) or "none"
        lines.append(f"| {record['qid']} run {record['run']} | {failed} | {', '.join(checks['caveats_missing']) or '—'} | "
                     f"{len(checks['estimates_as_reported'])} | {checks['saved_copy_mentions']} |")
    lines += ["", "```json", json.dumps(report["summary"], ensure_ascii=False, indent=2), "```", ""]
    (out / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def rescore(results: Path) -> dict:
    """Re-run the current checks on saved answers (no API or model calls), e.g. after tuning a
    detector. 中文：用当前的检查重新评一遍已保存的回答（不调 API、不调模型），比如调整检测规则之后。"""
    from eval.answer_checks import check_answer  # noqa: PLC0415

    report = json.loads(results.read_text(encoding="utf-8"))
    for record in report["records"]:
        if "answer" in record:
            record["checks"] = check_answer(record["answer"], context_from_json(record["context"]))
    report["rescored_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    write_report(results.parent, report)
    return report


def redact(message: str, secret: str | None) -> str:
    if secret:
        message = message.replace(secret, "[REDACTED]")
    return re.sub(r"AIza[0-9A-Za-z_\-]{20,}", "[REDACTED]", message)


def run(questions: list[dict], payloads: dict[str, dict], *, out: Path, runs: int, max_calls: int,
        stream_fn: Callable[[str], Iterable[str]] | None, secret: str | None = None) -> dict:
    """Ask each question `runs` times (stream_fn None = dry run: prompts only) and check every answer."""
    from eval.answer_checks import check_answer  # noqa: PLC0415
    from llm.prompts.chat_v4 import PROMPT_VERSION  # noqa: PLC0415

    (out / "answers").mkdir(parents=True, exist_ok=True)
    (out / "prompts").mkdir(parents=True, exist_ok=True)
    records, calls = [], 0
    for question in questions:
        prompt, context = build_case(question, payloads)
        (out / "prompts" / f"{question['qid']}.txt").write_text(prompt, encoding="utf-8")
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
    parser.add_argument("--dry-run", action="store_true", help="build prompts and contexts, no model calls")
    args = parser.parse_args(argv)
    if args.runs < 1 or args.max_calls < 1:
        parser.error("--runs and --max-calls must be at least 1")
    if args.rescore:
        report = rescore(args.rescore)
        print(json.dumps({"rescored": str(args.rescore), "status": report["status"], "summary": report["summary"]},
                         ensure_ascii=False))
        return exit_code(report)
    if not args.api_base or not args.out:
        parser.error("--api-base and --out are required unless --rescore is given")

    import httpx  # noqa: PLC0415

    questions = json.loads(args.questions.read_text(encoding="utf-8")) if args.questions else DEFAULT_QUESTIONS
    headers = {"X-Eval-Run": args.eval_run, "User-Agent": "neu-compass-answer-eval/1"}
    try:
        with httpx.Client(base_url=args.api_base.rstrip("/"), headers=headers, timeout=30.0) as client:
            payloads = fetch_courses(client, (cid for question in questions for cid in question["course_ids"]))
    except (httpx.HTTPError, RuntimeError) as exc:
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
