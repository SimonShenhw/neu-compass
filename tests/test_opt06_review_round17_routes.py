"""Round-17 review pins for the route evaluation: tie order, the BM25 leg, config provenance, guards and exit codes.
中文：第 17 轮评审的路由评测补钉：并列名次、BM25 一路、配置来源、隔离守卫、退出码。
"""

import copy
import importlib
import json
import os
import random
import socket
import sqlite3
import subprocess
import sys

import pytest


def cases(keep=None):
    from eval.route_eval import load_cases

    return [case for case in copy.deepcopy(load_cases()["cases"]) if keep is None or keep(case)]


def summary(report):
    turns = [(case["case_id"], turn["route_contract"]["verdict"], turn["route_contract"]["reasons"],
              turn["stream_contract"]["verdict"], turn["generation"]["verdict"], turn["generation_expectation"]["verdict"])
             for case in report["cases"] for turn in case["turns"]]
    counts = {key: {name: value for name, value in report[key].items() if name != "checks_summary"}
              for key in ("route_contract", "stream_contract", "generation")}
    return report["status"], report["expectation_mismatches"], counts, turns


@pytest.mark.parametrize("order", ["reversed", "shuffle:1", "shuffle:2", "shuffle:3"])
def test_verdicts_and_metrics_do_not_depend_on_faiss_tie_order(monkeypatch, order):
    import rag.index as index_mod
    from eval.route_eval import run_eval

    baseline = run_eval()
    original = index_mod.FaissIndex.add

    def permuted(self, vectors, course_ids, **kwargs):
        idx = list(range(len(course_ids)))
        if order == "reversed":
            idx.reverse()
        else:
            random.Random(int(order.split(":")[1])).shuffle(idx)
        if kwargs.get("fingerprints") is not None:
            kwargs["fingerprints"] = [kwargs["fingerprints"][i] for i in idx]
        return original(self, vectors[idx].copy(), [course_ids[i] for i in idx], **kwargs)

    monkeypatch.setattr(index_mod.FaissIndex, "add", permuted)
    assert summary(run_eval()) == summary(baseline)
    assert baseline["status"] == "complete"


@pytest.mark.parametrize("mode", ["empty", "reversed", "constant"])
def test_lexical_cases_detect_a_broken_bm25_leg(monkeypatch, mode):
    import numpy as np

    from eval.route_eval import run_eval
    from rag.hybrid import BM25Corpus, BM25Okapi

    lexical = cases(lambda case: case.get("lexical_required"))
    assert len(lexical) >= 5 and run_eval(lexical)["status"] == "complete"
    if mode == "constant":
        monkeypatch.setattr(BM25Okapi, "get_scores", lambda self, query: np.ones(self.corpus_size))
    else:
        original = BM25Corpus.search

        def broken(self, query, **kwargs):
            hits = original(self, query, **kwargs)
            return [] if mode == "empty" else hits[::-1]

        monkeypatch.setattr(BM25Corpus, "search", broken)
    report = run_eval(lexical)
    reasons = {case["case_id"]: turn["route_contract"]["reasons"] for case in report["cases"] for turn in case["turns"]}
    assert report["status"] == "failed"
    if mode == "empty":
        assert all("bm25_top_mismatch" in item for item in reasons.values())
    # F25c LOW-4: BM25 ranks DS 9019 (two query terms) above DS 9010 (one), against corpus order, so a reversed or
    # constant scorer fails here whatever the tie order. 中文：这条用例里 BM25 的顺序和语料顺序相反，倒序或常数打分都会失败。
    assert "bm25_top_mismatch" in reasons["lexical_reverse_order"]


def test_a_truncated_result_list_fails_every_hybrid_turn(monkeypatch):
    import api.routes.common as common
    from eval.route_eval import run_eval

    hybrid = cases(lambda case: case["case_id"] != "rescue_success"
                   and any(turn["expected"]["matched_via"] == "hybrid" for turn in case["turns"]))
    assert len(hybrid) >= 10 and run_eval(hybrid)["status"] == "complete"
    original = common.rerank_blend_with_rejection

    def short(*args, **kwargs):
        return original(*args, **{**kwargs, "top_k": 4})

    monkeypatch.setattr(common, "rerank_blend_with_rejection", short)
    report = run_eval(hybrid)
    turns = [turn for case in report["cases"] for turn in case["turns"]]
    assert all(len(turn["result_ids"]) == 4 and "result_count_mismatch" in turn["route_contract"]["reasons"] for turn in turns)


def test_settings_are_code_defaults_read_independently_and_compared_with_the_compose_file():
    from eval.route_eval import run_eval
    from eval.route_world import SETTING_NAMES, _same_value

    settings = run_eval(cases(lambda case: case["case_id"] == "alias_good"))["settings"]
    assert settings["profile"] == "code_defaults" and settings["deployment_verified"] is False
    assert settings["documented_deployment_source"] == "docker-compose.yml"
    for name in (*SETTING_NAMES, "blend_alpha", "reject_threshold"):
        item = settings[name]
        assert item["source"] == "code_default" and item["value"] == item["code_default"], name
        assert item["differs_from_documented_deployment"] == (not _same_value(item["code_default"], item["documented_deployment"]))
    assert settings["documented_deployment_differs"] == sorted(
        name for name in SETTING_NAMES if settings[name]["differs_from_documented_deployment"])
    # F25c NIT-6: the repository's compose file documents exactly these five deployed differences.
    assert settings["documented_deployment_differs"] == ["fusion_mode", "fusion_weight", "hyde_rescue", "rejection_mode",
                                                         "rerank_pool_size"]
    assert settings["k"] == {"value": 10, "source": "ui_default", "code_default": 10}


def test_the_compose_reader_takes_only_the_listed_environment_values(tmp_path, monkeypatch):
    import eval.route_world as world_mod

    (tmp_path / "docker-compose.yml").write_text(
        'services:\n  api:\n    environment:\n      RERANK_POOL_SIZE: "10"   # pool\n      FUSION_MODE: convex\n'
        '      HYDE_RESCUE: "true"\n      UNRELATED: "x"\n', encoding="utf-8")
    monkeypatch.setattr(world_mod, "ROOT", tmp_path)
    found = world_mod.documented_deployment()
    assert found["rerank_pool_size"] == "10" and found["fusion_mode"] == "convex" and found["hyde_rescue"] == "true"
    assert found["rejection_mode"] is None and "unrelated" not in found
    assert not world_mod._same_value(20, "10") and world_mod._same_value(False, None) and not world_mod._same_value(False, "true")


def test_the_compose_reader_handles_other_legal_spellings_and_only_the_api_service(tmp_path, monkeypatch):
    import eval.route_world as world_mod

    (tmp_path / "docker-compose.yml").write_text(
        "x-common: &common\n  restart: always\nservices:\n  ui:\n    environment:\n      FUSION_MODE: rrf\n"
        "    depends_on:\n      api:\n        condition: service_healthy\n"
        "  api:\n    image: synthetic\n    environment:\n      - \"FUSION_MODE=convex\"   # list form\n"
        "      - HYDE_RESCUE='false'\n      - RERANK_POOL_SIZE=${POOL:-10}\n      - FUSION_WEIGHT=${WEIGHT}\n"
        "      - REJECTION_MODE\n    ports:\n      - \"8000:8000\"\nvolumes:\n  ENABLE_RERANKER: \"false\"\n",
        encoding="utf-8")
    monkeypatch.setattr(world_mod, "ROOT", tmp_path)
    found = world_mod.documented_deployment()
    assert found["fusion_mode"] == "convex" and found["hyde_rescue"] == "false" and found["rerank_pool_size"] == "10"
    assert found["fusion_weight"] is None and found["rejection_mode"] is None and found["enable_reranker"] is None
    (tmp_path / "docker-compose.yml").write_text("services:\n  api:\n    environment:\n      ENABLE_RERANKER:\n", encoding="utf-8")
    assert world_mod.documented_deployment()["enable_reranker"] is None
    for written, same in (("1", True), ("TRUE", True), ("on", True), ("yes", True), ("0", False), ("no", False), ("maybe", None),
                          ("t", True), ("Y", True), ("f", False), ("n", False)):
        assert world_mod._same_value(True, written) is (same is True), written
        assert world_mod._same_value(False, written) is (same is False), written


def test_the_compose_reader_handles_indentless_lists_quoted_keys_and_host_values(tmp_path, monkeypatch):
    # F25d NIT-4: more legal spellings; null, ~, $VAR and an empty default leave the value to the host environment.
    import eval.route_world as world_mod

    monkeypatch.setattr(world_mod, "ROOT", tmp_path)
    (tmp_path / "docker-compose.yml").write_text(
        "﻿services:\n  \"api\":\n    environment:\n    - FUSION_MODE=convex\n    - RERANK_POOL_SIZE=$POOL\n"
        "    - HYDE_RESCUE=a$$b\n    - REJECTION_MODE=null\n    - FUSION_WEIGHT=\n    ports:\n    - \"8000:8000\"\n    labels:\n"
        "      ENABLE_RERANKER: \"false\"\n", encoding="utf-8")
    found = world_mod.documented_deployment()
    assert found["fusion_mode"] == "convex" and found["rerank_pool_size"] is None and found["hyde_rescue"] == "a$b"
    assert found["rejection_mode"] == "null" and found["fusion_weight"] == ""  # a list item is a plain string
    assert found["enable_reranker"] is None  # the block ends at the next key on its own level
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n  api:\n    environment:\n      \"FUSION_MODE\": convex\n      'REJECTION_MODE': threshold\n"
        "      HYDE_RESCUE: null\n      ENABLE_RERANKER: ~\n      FUSION_WEIGHT: ${WEIGHT:-}\n"
        "      RERANK_POOL_SIZE: \"null\"\n", encoding="utf-8")
    found = world_mod.documented_deployment()
    assert found["fusion_mode"] == "convex" and found["rejection_mode"] == "threshold"
    assert found["hyde_rescue"] is None and found["enable_reranker"] is None and found["fusion_weight"] is None
    assert found["rerank_pool_size"] == "null"


def test_each_audit_rule_refuses_and_counts(tmp_path):
    from eval.route_world import ROOT, SyntheticWorld

    (tmp_path / ".env").write_text("SYNTHETIC=1\n", encoding="utf-8")
    (tmp_path / "model.onnx").write_bytes(b"0")
    probes = [
        ("file_attempts", lambda: open(ROOT / "data" / "synthetic-absent.json", encoding="utf-8")),
        ("file_attempts", lambda: open(tmp_path / ".env", encoding="utf-8")),
        ("file_attempts", lambda: open(tmp_path / "model.onnx", "rb")),
        ("file_attempts", lambda: open(tmp_path / "written.txt", "w", encoding="utf-8")),
        ("file_attempts", lambda: sys.audit("os.chmod", str(tmp_path), 0o700, -1)),
        ("model_attempts", lambda: importlib.import_module("transformers.synthetic_probe_module")),
        ("network_attempts", lambda: socket.getaddrinfo("example.invalid", 80)),
        ("network_attempts", lambda: sys.audit("socket.bind", None, ("127.0.0.1", 0))),
        ("process_attempts", lambda: subprocess.Popen(["true"])),
        ("process_attempts", lambda: os.system("true")),
        ("process_attempts", lambda: sys.audit("os.posix_spawn", "true", ["true"], None)),
        ("database_attempts", lambda: sys.audit("sqlite3.load_extension", None, "synthetic")),
    ]
    with SyntheticWorld() as world:
        for category, probe in probes:
            before = dict(world.guard.counters)
            with pytest.raises(RuntimeError, match="forbidden"):
                probe()
            changed = {name for name, value in world.guard.counters.items() if value != before[name]}
            assert changed == {category} and world.guard.counters[category] == before[category] + 1, category
    assert not (tmp_path / "written.txt").exists()


# Every member of every deny set, written out here so that dropping one from eval/route_guard.py fails (F25c NIT-7).
DENIED_EVENTS = {
    "network_attempts": ("socket.connect", "socket.getaddrinfo", "socket.bind", "socket.sendto", "socket.sendmsg",
                         "socket.gethostbyname", "socket.gethostbyaddr"),
    "process_attempts": ("subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.fork", "os.forkpty", "os.spawn",
                         "os.startfile"),
    "file_attempts": ("os.mkdir", "os.remove", "os.rmdir", "os.rename", "os.link", "os.symlink", "os.truncate", "os.chmod",
                      "os.chown", "os.utime", "shutil.rmtree"),
    "database_attempts": ("sqlite3.enable_load_extension", "sqlite3.load_extension"),
}


@pytest.mark.parametrize("category, event", [(category, event) for category, events in DENIED_EVENTS.items() for event in events])
def test_every_denied_audit_event_refuses_and_counts(tmp_path, category, event):
    from eval.route_guard import OfflineGuard, OfflineViolation

    with OfflineGuard(tmp_path / "data") as guard:
        with pytest.raises(OfflineViolation):
            sys.audit(event)
    assert guard.counters == {**dict.fromkeys(guard.counters, 0), category: 1}


def test_attach_is_refused_on_the_world_and_on_fresh_connections(tmp_path):
    from eval.route_world import SyntheticWorld

    target = tmp_path / "attached.sqlite"
    with SyntheticWorld() as world:
        with pytest.raises(sqlite3.DatabaseError):
            world.conn.execute("ATTACH DATABASE ? AS other", (str(target),))
        fresh = sqlite3.connect(":memory:")
        try:
            with pytest.raises(sqlite3.DatabaseError):
                fresh.execute("ATTACH DATABASE ? AS other", (str(target),))
        finally:
            fresh.close()
        assert world.guard.counters["database_attempts"] == 2
    assert not target.exists()


SAVED_CONNECT = sqlite3.connect


@pytest.mark.parametrize("opener", ["dbapi2", "class", "_sqlite3", "saved_reference"])
def test_connections_opened_around_sqlite3_connect_are_refused_and_counted(tmp_path, opener):
    # F25c LOW-3: SQLite reads an attached file through its own VFS, so every other way to open a connection is refused.
    import _sqlite3
    import sqlite3.dbapi2

    from eval.route_guard import OfflineViolation
    from eval.route_world import SyntheticWorld

    open_one = {"dbapi2": sqlite3.dbapi2.connect, "class": sqlite3.Connection, "_sqlite3": _sqlite3.connect,
                "saved_reference": SAVED_CONNECT}[opener]
    with SyntheticWorld() as world:
        with pytest.raises(OfflineViolation):
            open_one(":memory:")
        assert world.guard.counters["database_attempts"] == 1
    open_one(":memory:").close()  # outside a world nothing is refused


def test_the_configured_database_and_index_paths_are_guarded_wherever_they_point(tmp_path, monkeypatch):
    from config import settings
    from eval.route_world import SyntheticWorld

    database, index = tmp_path / "configured.sqlite", tmp_path / "configured_index"
    database.write_bytes(b"x")
    index.mkdir()
    (index / "part").write_bytes(b"x")
    monkeypatch.setattr(settings, "sqlite_path", str(database))
    monkeypatch.setattr(settings, "faiss_index_path", str(index))
    with SyntheticWorld() as world:
        for path in (database, index / "part"):
            with pytest.raises(RuntimeError, match="forbidden"):
                open(path, "rb")
        assert world.guard.counters["file_attempts"] == 2


def test_worlds_refuse_nesting_and_a_dotenv_next_to_them(tmp_path, monkeypatch):
    from eval.route_world import SyntheticWorld

    with SyntheticWorld():
        with pytest.raises(RuntimeError, match="serially"):
            SyntheticWorld().__enter__()
    (tmp_path / ".env").write_text("SYNTHETIC=1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match=r"\.env"):
        SyntheticWorld().__enter__()


def test_a_refused_read_the_route_swallows_still_fails_the_run(monkeypatch):
    import api.routes.chat as chat
    from eval.route_eval import exit_code, run_eval
    from eval.route_world import ROOT

    original = chat.build_answer_evidence

    def swallowing(*args, **kwargs):
        try:
            open(ROOT / "data" / "synthetic-absent.json", encoding="utf-8")
        except RuntimeError:
            pass
        return original(*args, **kwargs)

    monkeypatch.setattr(chat, "build_answer_evidence", swallowing)
    report = run_eval(cases(lambda case: case["case_id"] == "alias_good"))
    assert report["isolation"]["file_attempts"] == 1 and report["route_contract"]["fail"] == 0
    assert report["status"] == "failed" and exit_code(report) == 1


def test_a_missing_fusion_trace_fails_every_leg_check(monkeypatch):
    from eval.route_eval import run_eval
    from eval.route_world import SyntheticWorld

    class Sink(list):
        def append(self, item):
            pass

    original = SyntheticWorld.__enter__

    def without_trace(self):
        world = original(self)
        world.retrieval_traces = Sink()
        return world

    monkeypatch.setattr(SyntheticWorld, "__enter__", without_trace)
    report = run_eval(cases(lambda case: case.get("vector_required") or case.get("lexical_required")))
    assert report["status"] == "failed"
    assert all("trace_missing" in turn["route_contract"]["reasons"] for case in report["cases"] for turn in case["turns"])


def test_history_that_does_not_reach_the_prompt_fails_the_route(monkeypatch):
    import api.routes.chat as chat
    from eval.route_eval import run_eval

    original = chat.build_prompt

    def without_history(*args, **kwargs):
        kwargs["history"] = []
        return original(*args, **kwargs)

    monkeypatch.setattr(chat, "build_prompt", without_history)
    turns = run_eval(cases(lambda case: case["case_id"] == "followup_good"))["cases"][0]["turns"]
    assert "history_not_in_prompt" not in turns[0]["route_contract"]["reasons"]
    assert "history_not_in_prompt" in turns[1]["route_contract"]["reasons"]


def test_more_results_than_k_and_a_wrong_top_group_fail_the_route():
    from eval import route_eval

    turn = {"request": {"k": 10}, "http_status": 200, "matched_via": "hybrid", "result_ids": [f"neu-cs-90{i:02d}" for i in range(1, 12)],
            "notices": []}
    expected = {"http_status": 200, "matched_via": "hybrid", "must_include": ["neu-cs-9001"], "notices": []}
    assert route_eval.score_retrieval(expected, turn)["reasons"] == ["k_exceeded"]
    turn["result_ids"] = ["neu-cs-9002", "neu-cs-9001", "neu-cs-9003"]
    in_any_order = route_eval.score_retrieval({**expected, "top_group": ["neu-cs-9001", "neu-cs-9002"]}, turn)
    assert in_any_order["verdict"] == "pass"
    wrong = route_eval.score_retrieval({**expected, "top_group": ["neu-cs-9001", "neu-cs-9003"]}, turn)
    assert wrong["reasons"] == ["top_group_mismatch"]
    assert route_eval.score_retrieval({**expected, "result_count": 3}, turn)["verdict"] == "pass"
    assert route_eval.score_retrieval({**expected, "result_count": 10}, turn)["reasons"] == ["result_count_mismatch"]


def test_packaged_metrics_count_the_whole_top_group():
    from eval.route_eval import run_eval

    metrics = run_eval(cases(lambda case: case.get("vector_required") or case.get("lexical_required")))["route_contract"]
    for key in ("hybrid_metrics", "vector_required_metrics", "lexical_required_metrics"):
        assert metrics[key]["relevant"] == "top_group_or_required"
        assert metrics[key]["recall_at_10"] == metrics[key]["mrr"] == 1.0, key


@pytest.mark.parametrize("change", ["no_query", "case_key", "required_and_forbidden", "long_group", "vector_flag",
                                    "lexical_flag", "k_five", "group_and_forbidden", "repeated_group",
                                    "repeated_vector", "repeated_bm25", "repeated_include", "hybrid_without_count",
                                    "count_above_k", "count_not_int", "repeated_exclude", "repeated_exact",
                                    "repeated_notice", "bm25_empty_and_top", "count_below_required", "count_not_exact",
                                    "long_group_without_count", "empty_leg"])
def test_more_case_mistakes_are_setup_errors(change):
    from eval.route_eval import _validate_cases, run_eval

    alias = change in ("repeated_exact", "count_not_exact", "long_group_without_count")
    case = cases(lambda item: item["case_id"] == ("alias_good" if alias else "vector_graph"))[0]
    turn = case["turns"][0]
    expected = turn["expected"]
    _validate_cases([copy.deepcopy(case)])  # the unchanged case is valid, so each change below is the only mistake
    if change == "no_query":
        del turn["request"]["query"]
    elif change == "case_key":
        case["vector_requried"] = True
    elif change == "required_and_forbidden":
        expected["must_exclude"] = ["neu-cs-9001"]
    elif change == "long_group":
        expected["top_group"] = [f"neu-cs-90{i:02d}" for i in range(1, 12)]
    elif change == "vector_flag":
        del expected["vector_top_any"]
    elif change == "lexical_flag":
        case["lexical_required"] = True
    elif change == "k_five":
        turn["request"]["k"] = 5
    # F25c NIT-5 and LOW-4: a case that could never pass, or a hybrid turn without a result count, is a setup error.
    elif change == "group_and_forbidden":
        expected["must_exclude"] = ["neu-cs-9009"]
    elif change == "repeated_group":
        expected["top_group"] = ["neu-cs-9001", "neu-cs-9001", "neu-cs-9011", "neu-cs-9020"]
    elif change == "repeated_vector":
        expected["vector_top_any"] = ["neu-cs-9001", "neu-cs-9001"]
    elif change == "repeated_bm25":
        expected["bm25_top_any"] = ["neu-cs-9001", "neu-cs-9001"]
    elif change == "repeated_include":
        expected["must_include"] = ["neu-cs-9001", "neu-cs-9001"]
    elif change == "hybrid_without_count":
        del expected["result_count"]
    elif change == "count_above_k":
        expected["result_count"] = 11
    elif change == "count_not_int":
        expected["result_count"] = True
    # F25d NIT-3 and NIT-5: more shapes that could never pass.
    elif change == "repeated_exclude":
        expected["must_exclude"] = ["neu-cs-9002", "neu-cs-9002"]
    elif change == "repeated_exact":
        expected["exact_ids"] = ["neu-cs-9001", "neu-cs-9001"]
    elif change == "repeated_notice":
        expected["notices"] = ["program_schedule_unverified", "program_schedule_unverified"]
    elif change == "bm25_empty_and_top":
        expected["bm25_top_any"] = ["neu-cs-9001"]
    elif change == "count_below_required":
        expected["result_count"] = 3
    elif change == "count_not_exact":
        expected["result_count"] = 2
    elif change == "long_group_without_count":  # a turn without result_count, so only the length rule applies
        expected["top_group"] = [f"neu-cs-90{i:02d}" for i in range(1, 12)]
    else:  # an empty leg list checks nothing
        expected["vector_top_any"] = []
    with pytest.raises(ValueError):
        run_eval([case])


def minimal_report(status):
    return {"status": status, "evidence_layer": "offline_synthetic", "population": {}, "route_contract": {"pass": 0, "fail": 0},
            "stream_contract": {"fail": 0}, "expectation_mismatches": 0, "isolation": {"file_attempts": 0},
            "database": {"accounting_errors": []}}


@pytest.mark.parametrize("outcome, code", [(RuntimeError("synthetic accounting mismatch"), 3), (KeyError("synthetic"), 3),
                                           ("isolation", 1), ("incomplete", 3), ("failed", 1), ("complete", 0)])
def test_cli_exit_codes_for_every_outcome(tmp_path, monkeypatch, capsys, outcome, code):
    from eval import route_eval
    from eval.route_guard import OfflineViolation
    from scripts import eval_route_offline as cli

    def fake():
        if outcome == "isolation":
            raise OfflineViolation("forbidden offline action: file_attempts")
        if isinstance(outcome, Exception):
            raise outcome
        return minimal_report(outcome)

    monkeypatch.setattr(route_eval, "run_eval", fake)
    assert cli.main(["--out", str(tmp_path / "out.json")]) == code
    if isinstance(outcome, str) and outcome != "isolation":
        line = json.loads(capsys.readouterr().out.splitlines()[-1])
        assert line["isolation"] == {"file_attempts": 0} and line["accounting_errors"] == []


def test_the_409_history_prefix_rescue_counts_forbidden_signals_and_bm25_empty_are_enforced(monkeypatch):
    from eval.route_eval import run_eval

    after_409 = run_eval(cases(lambda case: case["case_id"] == "followup_after_409"))["cases"][0]["turns"]
    assert after_409[1]["request"]["history"][1]["content"].startswith("🧭 ")
    rescue = cases(lambda case: case["case_id"] == "stream_rescue_failure")[0]
    rescue["turns"][0]["expected"]["rescue_calls"] = 0
    assert "rescue_calls_mismatch" in run_eval([rescue])["cases"][0]["turns"][0]["stream_contract"]["reasons"]
    numeric = cases(lambda case: case["case_id"] == "numeric_bad")[0]
    numeric["turns"][0]["expected_generation"] = {"verdict": "pass", "required_signals": [],
                                                  "forbidden_signals": ["estimates_as_reported"]}
    reasons = run_eval([numeric])["cases"][0]["turns"][0]["generation_expectation"]["reasons"]
    assert reasons == ["forbidden:estimates_as_reported"]
    lexical = cases(lambda case: case["case_id"] == "vector_graph")[0]
    lexical["turns"][0]["request"]["query"] = "traversal BFS"
    assert "lexical_dependency_present" in run_eval([lexical])["cases"][0]["turns"][0]["route_contract"]["reasons"]
