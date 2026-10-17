"""Offline synthetic /chat evaluation; retrieval and scripted-answer checks stay separate.

Complete means every fixture was executed, NOT that every answer passed, and never verifies
production quality. Expected HTTP decisions and stream failures remain in their denominators.
中文：完整运行不等于回答全过。保留每个失败／未检查项，不混合证据层级。
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from eval.answer_checks import HARD_FAILURES, check_answer, summarize
from scripts.eval_answers_live import (checker_identity, code_identity, context_from_records,
                                       context_to_json, course_records)

ROOT = Path(__file__).resolve().parents[1]
CASE_FILE = ROOT / "eval/route_cases_v1.json"
LAYER = "offline_synthetic"


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def load_cases():
    bundle = json.loads(CASE_FILE.read_text(encoding="utf-8"))
    _validate_cases(bundle["cases"])
    return bundle


def _validate_cases(cases):
    if not isinstance(cases, list) or not 1 <= len(cases) <= 100:
        raise ValueError("a bounded non-empty case list is required")
    seen = set()
    for case in cases:
        if not isinstance(case, dict) or not all(isinstance(case.get(key), str) and case[key]
                                               for key in ("case_id", "category", "answer_kind")):
            raise ValueError("case identity/category required")
        if case["case_id"] in seen or not isinstance(case.get("turns"), list) or not 1 <= len(case["turns"]) <= 12:
            raise ValueError("unique cases with bounded turns required")
        seen.add(case["case_id"])
        for turn in case["turns"]:
            if not isinstance(turn, dict) or not all(isinstance(turn.get(key), dict) for key in ("request", "stream", "expected")):
                raise ValueError("each turn needs request, stream and expected dictionaries")


def context_from_chat(meta, prompt, lang):
    """Use the actual emitted prompt and all meta evidence, not a reconstructed route.
    中文：从实际 prompt 和全部 meta 证据构造；身份或 notices 不一致时拒绝。"""
    block = prompt.split("# Retrieved course evidence (JSON DATA)\n", 1)[1].rsplit("\n\nAnswer:", 1)[0].strip()
    records = course_records(block)
    if [item["course_id"] for item in records] != [item["course_id"] for item in meta["results"]]:
        raise ValueError("prompt/meta course identity mismatch")
    notices = json.loads(prompt.split("# Retrieval notices (DATA)\n", 1)[1].split("\n\n# Retrieved", 1)[0])
    if notices != meta.get("notices", []):
        raise ValueError("prompt/meta notice mismatch")
    return context_from_records(block, [item["answer_evidence"] for item in meta["results"]],
                                lang=lang, notices=notices)


def score_retrieval(expected, actual):
    reasons, ids = [], set(actual["result_ids"])
    for name in ("http_status", "matched_via", "error_type"):
        if name in expected and actual[name] != expected[name]:
            reasons.append(f"{name}_mismatch")
    if "exact_ids" in expected and ids != set(expected["exact_ids"]):
        reasons.append("exact_ids_mismatch")
    if not set(expected.get("must_include", [])) <= ids:
        reasons.append("required_hit_missing")
    if ids & set(expected.get("must_exclude", [])):
        reasons.append("forbidden_hit_present")
    if actual["notices"] != expected.get("notices", []):
        reasons.append("notices_mismatch")
    if any(text not in actual.get("detail", "") for text in expected.get("detail_contains", [])):
        reasons.append("decision_detail_mismatch")
    return {"expected": expected, "verdict": "fail" if reasons else "pass", "reasons": reasons}


def execute_turn(world, client, turn, messages, tag):
    from app.chat_view import _context_course_ids, _recent_history

    request = {"k": 2, **turn["request"], "history": _recent_history(messages),
               "context_course_ids": _context_course_ids(messages), "allow_feedback_capture": False}
    world.set_stream(turn["stream"])
    prompts_before = len(world.prompts)
    messages.append({"role": "user", "content": request["query"]})
    response = client.post("/chat", json=request, headers={"X-Eval-Run": tag})
    result = {"request": request, "request_sha256": _digest(request), "http_status": response.status_code,
              "matched_via": None, "result_ids": [], "notices": [], "rejection_reason": None,
              "error_type": None, "prompt_sha256": None, "answer": "",
              "settings": {"hyde_rescue": world.settings.hyde_rescue}}
    if response.status_code != 200:
        assert len(world.prompts) == prompts_before
        body = response.json()
        result.update(error_type=f"http_{response.status_code}", detail=str(body.get("detail", "")))
        result["generation"] = {"verdict": "not_applicable", "checks": None}
        prefix = "🧭 " if response.status_code == 409 else "⚠️ Chat failed: "
        messages.append({"role": "assistant", "content": prefix + result["detail"], "evidence": []})
    else:
        events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
        if not events or events[0].get("type") != "meta" or events[-1].get("type") != "done":
            raise ValueError("incomplete event framing")
        if sum(event.get("type") == "meta" for event in events) != 1 or sum(event.get("type") == "done" for event in events) != 1:
            raise ValueError("duplicate event framing")
        if any(event.get("type") not in {"meta", "token", "error", "done"} for event in events):
            raise ValueError("unknown event")
        assert len(world.prompts) == prompts_before + 1
        meta, prompt = events[0], world.prompts[-1]
        errors = [event for event in events if event["type"] == "error"]
        if len(errors) > 1:
            raise ValueError("multiple stream errors")
        answer = "".join(event["text"] for event in events if event["type"] == "token")
        error_type = errors[0]["error_type"] if errors else None
        lang = turn.get("lang", "zh" if re.search(r"[一-鿿]", request["query"]) else "en")
        context = context_from_chat(meta, prompt, lang)
        checks = check_answer(answer, context) if answer.strip() else None
        if error_type == "no_answer" or (not answer.strip() and error_type is None):
            verdict = "no_answer"
        elif error_type:
            verdict = "stream_error"
        else:
            verdict = "hard_fail" if any(checks[name] for name in HARD_FAILURES) else "pass"
        result.update(matched_via=meta["matched_via"], result_ids=[item["course_id"] for item in meta["results"]],
                      notices=meta.get("notices", []), rejection_reason=meta.get("rejection_reason"),
                      error_type=error_type, prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
                      prompt_version=meta["prompt_version"], answer=answer, context=context_to_json(context),
                      generation={"verdict": verdict, "checks": checks})
        content = answer + ("\n\n⚠️ 提示：" + errors[0]["detail"] if errors else "")
        messages.append({"role": "assistant", "content": content, "evidence": meta["results"]})
    result["retrieval"] = score_retrieval(turn["expected"], result)
    return result


def _summaries(records, cases):
    population = {"cases_planned": len(cases), "cases_attempted": len(records),
                  "cases_completed": sum(not item["errored"] for item in records),
                  "cases_errored": sum(item["errored"] for item in records),
                  "cases_not_attempted": len(cases) - len(records),
                  "turns_planned": sum(len(item["turns"]) for item in cases),
                  "turns_attempted": sum(len(item["turns"]) for item in records)}
    turns = [turn for case in records for turn in case["turns"]]
    retrieval_counts = Counter(turn["retrieval"]["verdict"] for turn in turns)
    generation_counts = Counter(turn["generation"]["verdict"] for turn in turns)
    retrieval = {"planned": population["turns_planned"], "scored": retrieval_counts["pass"] + retrieval_counts["fail"],
                 "pass": retrieval_counts["pass"], "fail": retrieval_counts["fail"],
                 "not_scored": retrieval_counts["not_scored"], "by_category": {}}
    for category in sorted({item["category"] for item in cases}):
        counts = Counter(turn["retrieval"]["verdict"] for item in records if item["category"] == category for turn in item["turns"])
        retrieval["by_category"][category] = {"planned": sum(len(item["turns"]) for item in cases if item["category"] == category),
                                               "pass": counts["pass"], "fail": counts["fail"], "not_scored": counts["not_scored"]}
    metrics = []
    for case in records:
        for turn in case["turns"]:
            expected = turn["retrieval"].get("expected", {})
            gold = set(expected.get("must_include", expected.get("exact_ids", [])))
            if case["category"] == "alias_hybrid" and expected.get("matched_via") == "hybrid" and gold:
                hits = turn["result_ids"]
                metrics.append((len(gold & set(hits)) / len(gold),
                                next((1 / rank for rank, cid in enumerate(hits, 1) if cid in gold), 0.0)))
    retrieval["hybrid_metrics"] = {"n": len(metrics), "recall_at_k": sum(item[0] for item in metrics) / len(metrics) if metrics else None,
                                    "mrr": sum(item[1] for item in metrics) / len(metrics) if metrics else None}
    checked = [turn["generation"]["checks"] for turn in turns if turn["generation"]["verdict"] in {"pass", "hard_fail"}]
    generation = {"planned": population["turns_planned"], "checked": len(checked), "hard_fail": generation_counts["hard_fail"],
                  **{name: generation_counts[name] for name in ("stream_error", "no_answer", "not_applicable", "not_checked")},
                  "checks_summary": summarize(checked)}
    assert population["cases_planned"] == population["cases_completed"] + population["cases_errored"] + population["cases_not_attempted"]
    assert population["cases_attempted"] == len(cases) and population["turns_attempted"] == population["turns_planned"]
    assert retrieval["planned"] == retrieval["scored"] + retrieval["not_scored"]
    assert retrieval["scored"] == retrieval["pass"] + retrieval["fail"]
    assert generation["planned"] == sum(generation[key] for key in ("checked", "stream_error", "no_answer", "not_applicable", "not_checked"))
    return population, retrieval, generation


def run_eval(cases=None):
    from fastapi.testclient import TestClient
    from llm.prompts.chat_v4 import PROMPT_VERSION

    from eval.route_world import OFFLINE_CONFIG, TOPICS, SyntheticWorld

    bundle = load_cases()
    scope = "packaged" if cases is None else "provided"
    cases = copy.deepcopy(bundle["cases"] if cases is None else cases)
    _validate_cases(cases)
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    run_id, records = "opt06-" + uuid.uuid4().hex[:16], []
    with SyntheticWorld() as world, TestClient(world.app) as client:
        before, changes = world.snapshot(), world.conn.total_changes
        for case in cases:
            messages, outputs, errored = [], [], False
            for turn in case["turns"]:
                try:
                    result = execute_turn(world, client, turn, messages, run_id)
                except Exception as exc:  # A harness failure stays visible and does not drop later fixtures.
                    errored = True
                    result = {"request": turn["request"], "request_sha256": _digest(turn["request"]),
                              "http_status": None, "matched_via": None, "result_ids": [], "notices": [],
                              "error_type": "harness_error", "error_class": type(exc).__name__,
                              "error_detail": str(exc)[:300], "prompt_sha256": None, "answer": "",
                              "retrieval": {"expected": turn["expected"], "verdict": "not_scored", "reasons": ["harness_error"]},
                              "generation": {"verdict": "not_checked", "checks": None}}
                    messages.append({"role": "assistant", "content": "⚠️ Chat failed: synthetic harness failure", "evidence": []})
                outputs.append(result)
            records.append({"case_id": case["case_id"], "category": case["category"], "answer_kind": case["answer_kind"],
                            "errored": errored, "turns": outputs})
        logs = world.conn.execute("SELECT user_id FROM query_log ORDER BY log_id").fetchall()
        non_query_unchanged = world.snapshot() == before
        assert non_query_unchanged and world.conn.total_changes - changes == len(logs)
        assert all(row[0] == f"eval:{run_id}" for row in logs)
        database = {"query_log_rows": len(logs), "query_dml_changes": world.conn.total_changes - changes,
                    "query_log_user_ids": sorted({row[0] for row in logs}), "non_query_tables_unchanged": non_query_unchanged}
        world_sha256 = world.world_sha256
        real_model_calls, real_api_calls = world.real_model_calls, world.real_api_calls
    population, retrieval, generation = _summaries(records, cases)
    identity = code_identity()
    for name in ("eval/route_eval.py", "eval/route_world.py", "scripts/eval_route_offline.py"):
        identity["code_files_sha256"][name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
    return {"evidence_layer": LAYER, "real_model_calls": real_model_calls, "real_api_calls": real_api_calls,
            "production_quality_verified": False, "run_id": run_id, "started_utc": started,
            "finished_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "status": "incomplete" if population["cases_errored"] else "complete", **identity, **checker_identity(),
            "prompt_version": PROMPT_VERSION, "chat_v4_sha256": identity["code_files_sha256"]["llm/prompts/chat_v4.py"],
            "case_set_version": bundle["case_set_version"], "case_file_sha256": hashlib.sha256(CASE_FILE.read_bytes()).hexdigest(),
            "case_input_sha256": _digest(cases), "case_scope": scope, "data_kind": "synthetic", "world_sha256": world_sha256,
            "index": {"embedder": "synthetic_topic_vectors/1", "dimension": len(TOPICS), "reranker": "synthetic_word_overlap/1", "manifest": None},
            "settings": dict(OFFLINE_CONFIG), "population": population, "retrieval": retrieval, "generation": generation,
            "database": database, "cases": records}


def summarize_reports(reports):
    for report in reports:
        if report.get("evidence_layer") != LAYER:
            raise ValueError("cannot mix evidence layers")
        if any(type(report.get(name)) is not int or report[name] != 0 for name in ("real_model_calls", "real_api_calls")):
            raise ValueError("offline reports must have zero real calls")
        if report.get("production_quality_verified") is not False:
            raise ValueError("offline reports cannot verify production quality")
    return {"evidence_layer": LAYER, "runs": len(reports),
            "cases_planned": sum(report["population"]["cases_planned"] for report in reports)}
