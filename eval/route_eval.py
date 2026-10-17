"""Offline synthetic /chat evaluation; retrieval and scripted-answer checks stay separate.

Execution completeness, contract success and generation expectations are independent.
No synthetic result verifies production quality. All failures remain in their denominators.
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

from app.state_manager import DEFAULTS
from eval.answer_checks import HARD_FAILURES, check_answer, summarize
from scripts.eval_answers_live import (checker_identity, code_identity, context_from_records,
                                       context_to_json, course_records)

ROOT = Path(__file__).resolve().parents[1]
CASE_FILE = ROOT / "eval/route_cases_v1.json"
LAYER = "offline_synthetic"
UI_K = min(DEFAULTS["search_k"], 10)
SIGNALS = set(HARD_FAILURES) | {"estimates", "estimates_as_reported", "unattributed", "estimates_identity_unresolved",
                               "course_codes_outside_evidence", "conflicts_missing_values", "caveats_missing"}
GENERATION_STATES = {"pass", "hard_fail", "stream_error", "no_answer", "not_applicable", "unexpected_http", "not_checked"}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def exit_code(report):
    return 3 if report["status"] == "incomplete" else 1 if report["status"] == "failed" else 0


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
        if type(case.get("vector_required", False)) is not bool:
            raise ValueError("vector_required must be boolean")
        for turn in case["turns"]:
            if not isinstance(turn, dict) or not all(isinstance(turn.get(key), dict) for key in ("request", "stream", "expected")):
                raise ValueError("each turn needs request, stream and expected dictionaries")
            if type(turn["request"].get("k", UI_K)) is not int or turn["request"].get("k", UI_K) != UI_K:
                raise ValueError("this fixed profile uses the UI default k")
            expected = turn["expected"]
            required = {"http_status", "matched_via", "notices", "error_type", "rescue_calls"}
            allowed = required | {"exact_ids", "must_include", "must_exclude", "detail_contains", "vector_top_any", "bm25_empty"}
            if not required <= expected.keys() <= allowed or not {"exact_ids", "must_include"} & expected.keys():
                raise ValueError("expected needs explicit route, results, notices and stream contract keys")
            if type(expected["http_status"]) is not int or expected["http_status"] not in {200, 404, 409}:
                raise ValueError("invalid expected HTTP status")
            if expected["matched_via"] not in (None, "alias", "context", "program", "hybrid", "empty", "rejected"):
                raise ValueError("invalid expected matched_via")
            if type(expected["rescue_calls"]) is not int or expected["rescue_calls"] not in {0, 1}:
                raise ValueError("invalid rescue_calls")
            if expected["error_type"] not in (None, "http_404", "http_409", "upstream_error", "no_answer", "internal_error"):
                raise ValueError("invalid expected stream error")
            for name in ("exact_ids", "must_include", "must_exclude", "notices", "detail_contains", "vector_top_any"):
                if name in expected and (not isinstance(expected[name], list)
                        or not all(isinstance(item, str) and item for item in expected[name])):
                    raise ValueError(f"{name} must be a list of nonempty strings")
            if "bm25_empty" in expected and type(expected["bm25_empty"]) is not bool:
                raise ValueError("bm25_empty must be boolean")
            generation = turn.get("expected_generation")
            if not isinstance(generation, dict) or set(generation) != {"verdict", "required_signals", "forbidden_signals"}:
                raise ValueError("explicit expected_generation contract required")
            if not isinstance(generation["verdict"], str) or generation["verdict"] not in GENERATION_STATES:
                raise ValueError("unknown generation verdict")
            for key in ("required_signals", "forbidden_signals"):
                if not isinstance(generation[key], list) or any(not isinstance(item, str) or item not in SIGNALS for item in generation[key]):
                    raise ValueError("unknown generation signal")
            if set(generation["required_signals"]) & set(generation["forbidden_signals"]):
                raise ValueError("contradictory generation signals")


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
    for name in ("http_status", "matched_via"):
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
    traces = actual.get("retrieval_traces", [])
    if "vector_top_any" in expected and (not traces or not traces[0]["vector_ids"]
                                        or traces[0]["vector_ids"][0] not in expected["vector_top_any"]):
        reasons.append("vector_top_mismatch")
    if expected.get("bm25_empty") and (not traces or traces[0]["bm25_ids"]):
        reasons.append("lexical_dependency_present")
    return {"expected": expected, "verdict": "fail" if reasons else "pass", "reasons": reasons}


def score_stream(expected, actual):
    reasons = [f"{key}_mismatch" for key in ("error_type", "rescue_calls") if expected[key] != actual[key]]
    return {"verdict": "fail" if reasons else "pass", "reasons": reasons}


def score_generation(expected, actual):
    checks = actual["generation"]["checks"] or {}
    signals = {name: bool(checks.get(name)) for name in SIGNALS}
    signals["unattributed"] = any(item["kind"] == "unattributed" for item in checks.get("estimates", []))
    signals["estimates_identity_unresolved"] = any(item["identity"] in {"course_unresolved", "field_unresolved"}
                                                  for item in checks.get("estimates", []))
    reasons = (["verdict_mismatch"] if expected["verdict"] != actual["generation"]["verdict"] else [])
    reasons += ["required:" + name for name in expected["required_signals"] if not signals[name]]
    reasons += ["forbidden:" + name for name in expected["forbidden_signals"] if signals[name]]
    return {"expected": expected, "verdict": "fail" if reasons else "pass", "reasons": reasons}


def execute_turn(world, client, turn, messages, tag):
    from app.api_client import ApiClient, ApiError
    from app.chat_view import _context_course_ids, _recent_history

    request = {"k": UI_K, **turn["request"], "history": _recent_history(messages),
               "context_course_ids": _context_course_ids(messages), "allow_feedback_capture": False}
    world.last_request = request
    world.set_stream(turn["stream"])
    prompts_before = len(world.prompts)
    rescues_before, traces_before = world.rescue_calls, len(world.retrieval_traces)
    messages.append({"role": "user", "content": request["query"]})
    response = client.post("/chat", json=request, headers={"X-Eval-Run": tag})
    world.last_response_status = response.status_code
    result = {"request": request, "request_sha256": _digest(request), "http_status": response.status_code,
              "matched_via": None, "result_ids": [], "notices": [], "rejection_reason": None,
              "error_type": None, "prompt_sha256": None, "answer": "",
              "settings": {"hyde_rescue": {"value": world.settings.hyde_rescue, "source": "harness_pin" if turn["stream"].get("rescue") else "production"}}}
    if response.status_code != 200:
        require(len(world.prompts) == prompts_before, "HTTP decision unexpectedly generated a prompt")
        try:
            ApiClient._unwrap(response)
        except ApiError as exc:
            detail = exc.detail
        else:
            raise ValueError("non-200 response was not an API failure")
        result.update(error_type=f"http_{response.status_code}", detail=detail)
        verdict = "not_applicable" if response.status_code == turn["expected"]["http_status"] else "unexpected_http"
        result["generation"] = {"verdict": verdict, "checks": None}
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
        require(len(world.prompts) == prompts_before + 1, "stream seam did not capture exactly one prompt")
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
        content = answer + ((("\n\n" if answer else "") + "⚠️ " + errors[0]["detail"]) if errors else "")
        messages.append({"role": "assistant", "content": content, "evidence": meta["results"]})
    result.update(rescue_calls=world.rescue_calls - rescues_before, retrieval_traces=world.retrieval_traces[traces_before:])
    result["route_contract"] = score_retrieval(turn["expected"], result)
    result["stream_contract"] = score_stream(turn["expected"], result)
    result["generation_expectation"] = score_generation(turn["expected_generation"], result)
    return result


def _summaries(records, cases):
    population = {"cases_planned": len(cases), "cases_attempted": len(records),
                  "cases_completed": sum(not item["errored"] for item in records),
                  "cases_errored": sum(item["errored"] for item in records),
                  "cases_not_attempted": len(cases) - len(records),
                  "turns_planned": sum(len(item["turns"]) for item in cases),
                  "turns_attempted": sum(len(item["turns"]) for item in records)}
    turns = [turn for case in records for turn in case["turns"]]
    retrieval_counts = Counter(turn["route_contract"]["verdict"] for turn in turns)
    generation_counts = Counter(turn["generation"]["verdict"] for turn in turns)
    retrieval = {"planned": population["turns_planned"], "scored": retrieval_counts["pass"] + retrieval_counts["fail"],
                 "pass": retrieval_counts["pass"], "fail": retrieval_counts["fail"],
                 "not_scored": retrieval_counts["not_scored"], "by_category": {}}
    for category in sorted({item["category"] for item in cases}):
        counts = Counter(turn["route_contract"]["verdict"] for item in records if item["category"] == category for turn in item["turns"])
        retrieval["by_category"][category] = {"planned": sum(len(item["turns"]) for item in cases if item["category"] == category),
                                               "pass": counts["pass"], "fail": counts["fail"], "not_scored": counts["not_scored"]}
    metrics, vector_metrics = [], []
    for case in records:
        for turn in case["turns"]:
            expected = turn["route_contract"].get("expected", {})
            gold = set(expected.get("must_include", expected.get("exact_ids", [])))
            if case["category"] == "alias_hybrid" and expected.get("matched_via") == "hybrid" and gold:
                hits = turn["result_ids"]
                metrics.append((len(gold & set(hits)) / len(gold),
                                next((1 / rank for rank, cid in enumerate(hits, 1) if cid in gold), 0.0)))
                if case.get("vector_required"):
                    vector_metrics.append(metrics[-1])
    for key, values in (("hybrid_metrics", metrics), ("vector_required_metrics", vector_metrics)):
        retrieval[key] = {"n": len(values), "k": UI_K, "recall_at_10": sum(item[0] for item in values) / len(values) if values else None,
                          "mrr": sum(item[1] for item in values) / len(values) if values else None}
    checked = [turn["generation"]["checks"] for turn in turns if turn["generation"]["verdict"] in {"pass", "hard_fail"}]
    generation = {"planned": population["turns_planned"], "checked": len(checked), "hard_fail": generation_counts["hard_fail"],
                  **{name: generation_counts[name] for name in ("stream_error", "no_answer", "not_applicable", "unexpected_http", "not_checked")},
                  "partial_hard_fail": sum(turn["generation"]["verdict"] == "stream_error" and bool(turn["generation"]["checks"])
                                           and any(turn["generation"]["checks"][name] for name in HARD_FAILURES) for turn in turns),
                  "checks_summary": summarize(checked)}
    require(population["cases_planned"] == population["cases_completed"] + population["cases_errored"] + population["cases_not_attempted"], "case accounting mismatch")
    require(population["cases_attempted"] == len(cases) and population["turns_attempted"] == population["turns_planned"], "turn accounting mismatch")
    require(retrieval["planned"] == retrieval["scored"] + retrieval["not_scored"], "route accounting mismatch")
    require(retrieval["scored"] == retrieval["pass"] + retrieval["fail"], "route score mismatch")
    require(generation["planned"] == sum(generation[key] for key in ("checked", "stream_error", "no_answer", "not_applicable", "unexpected_http", "not_checked")), "generation accounting mismatch")
    return population, retrieval, generation


def run_eval(cases=None, *, vector_mode="normal"):
    from fastapi.testclient import TestClient
    from llm.prompts.chat_v4 import PROMPT_VERSION

    from eval.route_world import ROWS, TOPICS, SyntheticWorld

    bundle = load_cases()
    scope = "packaged" if cases is None else "provided"
    cases = copy.deepcopy(bundle["cases"] if cases is None else cases)
    _validate_cases(cases)
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    run_id, records = "opt06-" + uuid.uuid4().hex[:16], []
    with SyntheticWorld(vector_mode=vector_mode) as world, TestClient(world.app) as client:
        before, changes = world.snapshot(), world.conn.total_changes
        for case in cases:
            messages, outputs, errored = [], [], False
            for turn in case["turns"]:
                world.last_response_status, world.last_request = None, turn["request"]
                try:
                    result = execute_turn(world, client, turn, messages, run_id)
                except Exception as exc:  # A harness failure stays visible and does not drop later fixtures.
                    errored = True
                    result = {"request": world.last_request, "request_sha256": _digest(world.last_request),
                              "http_status": world.last_response_status, "matched_via": None, "result_ids": [], "notices": [],
                              "error_type": "harness_error", "error_class": type(exc).__name__,
                              "error_detail": str(exc)[:300], "prompt_sha256": None, "answer": "",
                              "route_contract": {"expected": turn["expected"], "verdict": "not_scored", "reasons": ["harness_error"]},
                              "stream_contract": {"verdict": "not_scored", "reasons": ["harness_error"]},
                              "generation_expectation": {"expected": turn["expected_generation"], "verdict": "fail", "reasons": ["harness_error"]},
                              "generation": {"verdict": "not_checked", "checks": None}}
                    if not messages or messages[-1]["role"] != "user":
                        messages.append({"role": "user", "content": world.last_request["query"]})
                    messages.append({"role": "assistant", "content": "⚠️ Chat failed: synthetic harness failure", "evidence": []})
                outputs.append(result)
            records.append({"case_id": case["case_id"], "category": case["category"], "answer_kind": case["answer_kind"],
                            "vector_required": case.get("vector_required", False), "errored": errored, "turns": outputs})
        logs = world.conn.execute("SELECT user_id FROM query_log ORDER BY log_id").fetchall()
        non_query_unchanged = world.snapshot() == before
        http_200 = sum(turn["http_status"] == 200 for record in records for turn in record["turns"])
        accounting_errors = []
        for condition, message in (
            (non_query_unchanged and world.conn.total_changes - changes == len(logs), "unexpected database DML"),
            (all(row[0] == f"eval:{run_id}" for row in logs), "query_log without eval tag"),
            (len(logs) == http_200, "query_log rows do not equal successful HTTP turns"),
        ):
            try:
                require(condition, message)
            except RuntimeError as exc:
                accounting_errors.append(str(exc))
        database = {"query_log_rows": len(logs), "query_dml_changes": world.conn.total_changes - changes,
                    "query_log_user_ids": sorted({row[0] for row in logs}), "non_query_tables_unchanged": non_query_unchanged,
                    "http_200_turns": http_200, "accounting_errors": accounting_errors}
        world_sha256 = world.world_sha256
        real_model_calls, real_api_calls = world.real_model_calls, world.real_api_calls
        isolation, config = dict(world.guard.counters), copy.deepcopy(world.config)
    population, retrieval, generation = _summaries(records, cases)
    stream_counts = Counter(turn["stream_contract"]["verdict"] for record in records for turn in record["turns"])
    stream_contract = {"planned": population["turns_planned"], **{key: stream_counts[key] for key in ("pass", "fail", "not_scored")}}
    require(stream_contract["planned"] == sum(stream_contract[key] for key in ("pass", "fail", "not_scored")), "stream accounting mismatch")
    mismatches = sum(turn["generation_expectation"]["verdict"] == "fail" for record in records for turn in record["turns"])
    status = ("incomplete" if population["cases_errored"] else
              "failed" if retrieval["fail"] or stream_contract["fail"] or mismatches or any(isolation.values()) or accounting_errors else "complete")
    identity = code_identity()
    for name in ("eval/route_eval.py", "eval/route_world.py", "eval/route_guard.py", "scripts/eval_route_offline.py"):
        identity["code_files_sha256"][name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
    return {"evidence_layer": LAYER, "real_model_calls": real_model_calls, "real_api_calls": real_api_calls,
            "production_quality_verified": False, "run_id": run_id, "started_utc": started,
            "finished_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "status": status, "execution_status": "incomplete" if population["cases_errored"] else "complete",
            "expectation_mismatches": mismatches, "isolation": isolation, **identity, **checker_identity(),
            "prompt_version": PROMPT_VERSION, "chat_v4_sha256": identity["code_files_sha256"]["llm/prompts/chat_v4.py"],
            "case_set_version": bundle["case_set_version"], "case_file_sha256": hashlib.sha256(CASE_FILE.read_bytes()).hexdigest(),
            "case_input_sha256": _digest(cases), "case_scope": scope, "data_kind": "synthetic", "world_sha256": world_sha256,
            "index": {"embedder": "synthetic_topic_vectors/2", "vector_mode": vector_mode, "dimension": len(TOPICS),
                      "reranker": "synthetic_semantic_lexical/2", "manifest": None, "course_count": len(ROWS)},
            "settings": {**config, "k": {"value": UI_K, "source": "production", "production_default": UI_K}},
            "population": population, "route_contract": retrieval, "stream_contract": stream_contract, "generation": generation,
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
