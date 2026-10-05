"""Actual isolated SQLite/CLI sync; preserves legacy and Course columns."""

from __future__ import annotations

import copy
import json
import hashlib
import pickle
import sqlite3
from datetime import date
import subprocess
import sys
from pathlib import Path

import pytest

from db.connection import connect
from db.program_plan_repository import (
    PlanDowngradeError,
    ProgramPlanRepository,
    RecordedProvenance,
    provenance_downgrade,
)
from db.program_repository import ProgramRepository
from db.repository import CourseRepository
from schemas.course import Course
from schemas.program import Program, ProgramRequiredCourse
from schemas.program_plan import ProgramPlan
from scripts.init_db import init_database
from scripts.sync_program_plans import sync_plans

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data/program_plan_seed/boston_2026_2027_core_fragments.json"


@pytest.fixture
def runtime(tmp_path):
    path, file = tmp_path / "runtime.db", tmp_path / "plans.json"
    init_database(path)
    conn = connect(path)
    for family in ["cs-ms", "ds-ms", "info-ms"]:
        ProgramRepository(conn).add_program(Program(program_id=family, full_name="Legacy unverified seed", prefix=family.split("-")[0].upper()))
    CourseRepository(conn).insert(Course(course_id="old", primary_code="CS 5800", primary_name="Algorithms"), raw_text="Mixed old text")
    CourseRepository(conn).mark_indexed("old")
    ProgramRepository(conn).add_required_course(ProgramRequiredCourse(program_id="cs-ms", course_id="old", requirement_type="core", semester_recommended=1))
    conn.execute("DROP TABLE program_plans")
    conn.execute("DELETE FROM schema_versions WHERE version='1.5'")
    conn.commit()
    conn.close()
    file.write_text(SOURCE.read_text(encoding="utf-8"), encoding="utf-8")
    return path, file


def existing_rows(path):
    conn = connect(path)
    try:
        return {table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY 1")]
                for table in ["courses", "programs", "program_required_courses", "course_prerequisites"]}
    finally:
        conn.close()


def test_sync_defaults_to_read_only_then_atomic_additive_idempotent(runtime):
    path, file = runtime
    before, old_rows = path.read_bytes(), existing_rows(path)
    dry = sync_plans(path, file)
    assert dry["schema_missing"] is True and dry["committed"] is False and dry["would_store"] == 3
    assert path.read_bytes() == before
    committed = sync_plans(path, file, commit=True)
    assert committed["stored"] == 3
    assert existing_rows(path) == old_rows
    conn = connect(path)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    stored_before = conn.execute("SELECT document FROM program_plans ORDER BY plan_id").fetchall()
    conn.close()
    assert sync_plans(path, file, commit=True)["stored"] == 0
    conn = connect(path)
    assert [tuple(row) for row in conn.execute("SELECT document FROM program_plans ORDER BY plan_id")] == [tuple(row) for row in stored_before]
    conn.close()


@pytest.mark.parametrize("kind", ["bad-json", "bad-url", "duplicate-id", "duplicate-scope", "not-array"])
def test_invalid_file_aborts_before_ddl(runtime, kind):
    path, file = runtime
    data = json.loads(file.read_text(encoding="utf-8"))
    if kind == "bad-json":
        file.write_text("not-json", encoding="utf-8")
    else:
        if kind == "bad-url":
            data[1]["source_url"] = "https://evil.test/"
        elif kind == "duplicate-id":
            data[1]["plan_id"] = data[0]["plan_id"]
        elif kind == "duplicate-scope":
            extra = {**data[0], "plan_id": "different-id"}
            data.append(extra)
        else:
            data = {}
        file.write_text(json.dumps(data), encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(ValueError):
        sync_plans(path, file, commit=True)
    assert path.read_bytes() == before


def test_late_missing_program_rolls_back_prior_store_and_new_schema(runtime):
    path, file = runtime
    data = json.loads(file.read_text(encoding="utf-8"))
    data[1]["program_id"] = "missing"
    file.write_text(json.dumps(data), encoding="utf-8")
    old_rows = existing_rows(path)
    with pytest.raises(ValueError, match="unseeded"):
        sync_plans(path, file, commit=True)
    conn = connect(path)
    assert not ProgramPlanRepository(conn).available()
    assert conn.execute("SELECT 1 FROM schema_versions WHERE version='1.5'").fetchone() is None
    conn.close()
    assert existing_rows(path) == old_rows


@pytest.mark.parametrize("change", ["scope", "replacement-id"])
def test_scope_is_immutable_and_unique_in_dry_and_commit(runtime, change):
    path, file = runtime
    sync_plans(path, file, commit=True)
    data = json.loads(file.read_text(encoding="utf-8"))[:1]
    if change == "scope":
        data[0]["campus"] = "seattle"
    else:
        data[0]["plan_id"] = "replacement-id"
    file.write_text(json.dumps(data), encoding="utf-8")
    for commit in [False, True]:
        with pytest.raises(ValueError):
            sync_plans(path, file, commit=commit)


def test_corrupt_content_is_hidden_and_sync_repairs_without_rebinding_scope(runtime):
    path, file = runtime
    sync_plans(path, file, commit=True)
    conn = connect(path)
    data = json.loads(conn.execute("SELECT document FROM program_plans WHERE program_id='cs-ms'").fetchone()[0])
    data["notes"] = "Changed without updating content hash"
    conn.execute("UPDATE program_plans SET document=? WHERE program_id='cs-ms'", (json.dumps(data),))
    conn.commit()
    assert ProgramPlanRepository(conn).list_for_program("cs-ms") == []
    conn.close()
    assert sync_plans(path, file)["would_store"] == 1
    assert sync_plans(path, file, commit=True)["stored"] == 1


def test_store_revalidates_model_copy_to_prevent_validation_bypass(runtime):
    path, file = runtime
    sync_plans(path, file, commit=True)
    conn = connect(path)
    plan = ProgramPlanRepository(conn).list_for_program("cs-ms")[0]
    with pytest.raises(ValueError):
        ProgramPlanRepository(conn).store(plan.model_copy(update={"source_url": "javascript:bad"}))
    conn.close()


def test_actual_cli_read_only_then_explicit_commit(runtime):
    path, file = runtime
    command = [sys.executable, str(ROOT / "scripts/sync_program_plans.py"), "--db-path", str(path), "--plan-file", str(file)]
    dry = subprocess.run(command, capture_output=True, text=True, timeout=45)
    assert dry.returncode == 0, dry.stdout + dry.stderr
    assert json.loads(dry.stdout)["committed"] is False
    written = subprocess.run([*command, "--commit"], capture_output=True, text=True, timeout=45)
    assert written.returncode == 0, written.stdout + written.stderr
    assert json.loads(written.stdout)["stored"] == 3


def test_typo_database_is_not_created(tmp_path):
    missing = tmp_path / "does-not-exist.db"
    with pytest.raises(FileNotFoundError):
        sync_plans(missing, SOURCE)
    assert not missing.exists()


def test_foreign_key_cascade_does_not_leave_orphan_plan(runtime):
    path, file = runtime
    sync_plans(path, file, commit=True)
    conn = connect(path)
    conn.execute("DELETE FROM programs WHERE program_id='cs-ms'")
    assert ProgramPlanRepository(conn).list_for_program("cs-ms") == []
    conn.close()


CS_PLAN = "cs-ms-boston-2026-2027-standard"


def stored_documents(path):
    conn = connect(path)
    try:
        return [tuple(row) for row in conn.execute("SELECT plan_id, document, content_hash FROM program_plans ORDER BY plan_id")]
    finally:
        conn.close()


def fingerprint_stored_plan(path, plan_id, digest="a" * 64):
    """Upgrade one stored core plan in place, the way the extended layer does."""
    raw = next(item for item in json.loads(SOURCE.read_text(encoding="utf-8")) if item["plan_id"] == plan_id)
    upgraded = ProgramPlan.model_validate({**raw, "source_html_sha256": digest})
    conn = connect(path)
    try:
        assert ProgramPlanRepository(conn).store(upgraded) is True
        conn.commit()
    finally:
        conn.close()
    return upgraded


def test_weaker_layer_is_refused_as_a_whole_in_dry_run_and_commit(runtime):
    """Nothing in a refused file is written, including its plans that are not downgrades."""
    path, file = runtime
    sync_plans(path, file, commit=True)
    upgraded = fingerprint_stored_plan(path, CS_PLAN)
    data = json.loads(file.read_text(encoding="utf-8"))
    edited = next(item for item in data if item["program_id"] == "ds-ms")
    edited["notes"] += " Edited after import."
    file.write_text(json.dumps(data), encoding="utf-8")
    before = stored_documents(path)
    for commit in [False, True]:
        with pytest.raises(PlanDowngradeError) as refused:
            sync_plans(path, file, commit=commit)
        assert refused.value.downgrades == [{"plan_id": CS_PLAN, "reason": "drops_source_fingerprint"}]
        assert stored_documents(path) == before
    conn = connect(path)
    assert ProgramPlanRepository(conn).list_for_program("cs-ms") == [upgraded]
    conn.close()


def test_allow_downgrade_reports_and_replaces_deliberately(runtime):
    path, file = runtime
    sync_plans(path, file, commit=True)
    fingerprint_stored_plan(path, CS_PLAN)
    expected = [{"plan_id": CS_PLAN, "reason": "drops_source_fingerprint"}]
    dry = sync_plans(path, file, allow_downgrade=True)
    assert dry["downgraded"] == expected and dry["would_store"] == 1
    committed = sync_plans(path, file, commit=True, allow_downgrade=True)
    assert committed["downgraded"] == expected and committed["stored"] == 1
    conn = connect(path)
    assert [plan.source_html_sha256 for plan in ProgramPlanRepository(conn).list_for_program("cs-ms")] == [None]
    conn.close()
    assert "downgraded" not in sync_plans(path, file)


def test_store_guards_provenance_but_allows_upgrade_recapture_and_repair(runtime):
    path, file = runtime
    sync_plans(path, file, commit=True)
    conn = connect(path)
    repo = ProgramPlanRepository(conn)
    core = repo.list_for_program("cs-ms")[0]
    assert core.review_status == "source_checked" and core.source_html_sha256 is None
    with pytest.raises(PlanDowngradeError, match="drops_source_review"):
        repo.store(core.model_copy(update={"review_status": "draft"}))
    assert repo.store(core.model_copy(update={"source_html_sha256": "a" * 64})) is True
    assert repo.store(core.model_copy(update={"source_html_sha256": "b" * 64})) is True
    with pytest.raises(PlanDowngradeError, match="drops_source_fingerprint"):
        repo.store(core)
    assert repo.store(core, allow_downgrade=True) is True
    recaptured = core.model_copy(update={"source_html_sha256": "c" * 64})
    assert repo.store(recaptured) is True
    # A row failing its integrity check is hidden from readers, but what it records still
    # counts: a weaker document is refused, an equally verified one repairs it.
    conn.execute("UPDATE program_plans SET content_hash=? WHERE plan_id=?", ("0" * 64, CS_PLAN))
    assert repo.list_for_program("cs-ms") == []
    with pytest.raises(PlanDowngradeError, match="drops_source_fingerprint"):
        repo.store(core)
    assert repo.store(recaptured) is True
    assert repo.list_for_program("cs-ms") == [recaptured]
    # A row that no longer parses as a plan records nothing, so any valid document repairs it.
    conn.execute("UPDATE program_plans SET document='{}' WHERE plan_id=?", (CS_PLAN,))
    assert repo.store(core) is True
    assert repo.list_for_program("cs-ms") == [core]
    conn.close()


def test_provenance_rules_and_which_reason_wins():
    # Dates are pinned here, not taken from the seed, which a re-capture would move.
    raw = {**json.loads(SOURCE.read_text(encoding="utf-8"))[0], "captured_on": "2026-10-01", "checked_on": "2026-10-01"}
    plain = ProgramPlan.model_validate(raw)
    fingerprinted = plain.model_copy(update={"source_html_sha256": "a" * 64})
    assert provenance_downgrade(None, plain) is None
    assert provenance_downgrade(plain, fingerprinted) is None
    unfingerprinted_draft = plain.model_copy(update={"review_status": "draft"})
    assert provenance_downgrade(fingerprinted, unfingerprinted_draft) == "drops_source_fingerprint"
    assert provenance_downgrade(plain, unfingerprinted_draft) == "drops_source_review"
    later = ProgramPlan.model_validate({**raw, "source_html_sha256": "b" * 64,
                                        "captured_on": "2026-10-02", "checked_on": "2026-10-02"})
    assert provenance_downgrade(later, fingerprinted) == "drops_newer_capture"
    assert provenance_downgrade(fingerprinted, later) is None
    assert provenance_downgrade(fingerprinted, fingerprinted.model_copy(update={"source_html_sha256": "c" * 64})) is None
    assert provenance_downgrade(later, later) is None
    # Rule 3 compares capture dates, not review dates, and only between two fingerprints.
    stored_capture = ProgramPlan.model_validate({**raw, "source_html_sha256": "a" * 64,
                                                 "captured_on": "2026-10-03", "checked_on": "2026-10-03"})
    older_capture_checked_later = ProgramPlan.model_validate({**raw, "source_html_sha256": "c" * 64,
                                                              "captured_on": "2026-10-01", "checked_on": "2026-10-05"})
    assert provenance_downgrade(stored_capture, older_capture_checked_later) == "drops_newer_capture"
    newer_plain = ProgramPlan.model_validate({**raw, "captured_on": "2026-10-02", "checked_on": "2026-10-02"})
    assert provenance_downgrade(newer_plain, fingerprinted) is None
    # The same fingerprint is the same capture, whatever date a copy carries.
    assert provenance_downgrade(later, later.model_copy(update={"captured_on": date(2026, 10, 1)})) is None
    # Review is checked before the capture date.
    assert provenance_downgrade(later, fingerprinted.model_copy(update={"review_status": "draft"})) == "drops_source_review"
    # Only a source_checked prior is protected by review: drafts may replace drafts or be upgraded.
    draft = unfingerprinted_draft
    assert provenance_downgrade(draft, draft.model_copy(update={"notes": draft.notes + " Edited."})) is None
    assert provenance_downgrade(draft, plain) is None
    # The leniently read record of a stored row obeys the same rules.
    assert provenance_downgrade(RecordedProvenance("a" * 64, "source_checked", date(2026, 10, 1)), plain) == "drops_source_fingerprint"
    assert provenance_downgrade(RecordedProvenance(None, None, None), plain) is None
    assert provenance_downgrade(RecordedProvenance(None, None, None), draft) is None
    assert provenance_downgrade(RecordedProvenance("b" * 64, "source_checked", None), fingerprinted) is None


def test_store_compares_the_stored_capture_date_not_the_review_date(runtime):
    path, file = runtime
    sync_plans(path, file, commit=True)
    raw = {**next(item for item in json.loads(SOURCE.read_text(encoding="utf-8")) if item["plan_id"] == CS_PLAN),
           "captured_on": "2026-10-01", "checked_on": "2026-10-01"}
    newer = ProgramPlan.model_validate({**raw, "source_html_sha256": "b" * 64,
                                        "captured_on": "2026-10-03", "checked_on": "2026-10-05"})
    recapture = ProgramPlan.model_validate({**raw, "source_html_sha256": "c" * 64,
                                            "captured_on": "2026-10-04", "checked_on": "2026-10-04"})
    older = ProgramPlan.model_validate({**raw, "source_html_sha256": "a" * 64})
    conn = connect(path)
    repo = ProgramPlanRepository(conn)
    assert repo.store(newer) is True
    # Captured after the stored 10-03 capture, though before its 10-05 review: a re-capture.
    assert repo.store(recapture) is True
    with pytest.raises(PlanDowngradeError, match="drops_newer_capture"):
        repo.store(older)
    assert repo.store(older, allow_downgrade=True) is True
    conn.close()


def test_downgrade_error_survives_pickle_and_copy():
    plain = PlanDowngradeError([{"plan_id": CS_PLAN, "reason": "drops_source_fingerprint"}])
    noted = PlanDowngradeError([{"plan_id": CS_PLAN, "reason": "drops_newer_capture"}])
    noted.add_note("seen during a release rehearsal")
    for error in (plain, noted):
        for clone in (pickle.loads(pickle.dumps(error)), copy.copy(error), copy.deepcopy(error)):
            assert type(clone) is PlanDowngradeError
            assert clone.downgrades == error.downgrades and str(clone) == str(error)
            assert getattr(clone, "__notes__", None) == getattr(error, "__notes__", None)


def core_plan(plan_id):
    return ProgramPlan.model_validate(next(item for item in json.loads(SOURCE.read_text(encoding="utf-8"))
                                           if item["plan_id"] == plan_id))


def test_a_row_failing_plan_validation_keeps_its_recorded_provenance(runtime):
    """A field from another build (extra="forbid") or a tightened validator must not switch the guard off."""
    path, file = runtime
    sync_plans(path, file, commit=True)
    fingerprint_stored_plan(path, CS_PLAN)
    conn = connect(path)
    conn.execute("UPDATE program_plans SET document=json_set(document, '$.field_from_another_build', 'x') "
                 "WHERE plan_id=?", (CS_PLAN,))
    conn.commit()
    with pytest.raises(PlanDowngradeError, match="drops_source_fingerprint"):
        ProgramPlanRepository(conn).store(core_plan(CS_PLAN))
    conn.close()
    before = stored_documents(path)
    for commit in [False, True]:
        with pytest.raises(PlanDowngradeError) as refused:
            sync_plans(path, file, commit=commit)
        assert refused.value.downgrades == [{"plan_id": CS_PLAN, "reason": "drops_source_fingerprint"}]
        assert stored_documents(path) == before


def with_cs_plan_as_draft(file):
    data = json.loads(file.read_text(encoding="utf-8"))
    for item in data:
        if item["plan_id"] == CS_PLAN:
            item["review_status"] = "draft"
    file.write_text(json.dumps(data), encoding="utf-8")
    return ProgramPlan.model_validate(next(item for item in data if item["plan_id"] == CS_PLAN))


def test_sync_lets_even_a_draft_overwrite_a_row_that_records_no_provenance(runtime):
    path, file = runtime
    sync_plans(path, file, commit=True)
    conn = connect(path)
    conn.execute("UPDATE program_plans SET document='{}' WHERE plan_id=?", (CS_PLAN,))
    conn.commit()
    conn.close()
    draft = with_cs_plan_as_draft(file)
    assert sync_plans(path, file)["would_store"] == 1
    assert sync_plans(path, file, commit=True)["stored"] == 1
    conn = connect(path)
    assert ProgramPlanRepository(conn).list_for_program("cs-ms") == [draft]
    conn.close()


def test_files_with_draft_plans_can_be_replayed_and_edited(runtime):
    """Review only protects a source_checked prior, and the pre-pass judges unchanged plans too."""
    path, file = runtime
    draft = with_cs_plan_as_draft(file)
    assert sync_plans(path, file, commit=True)["stored"] == 3
    assert sync_plans(path, file)["would_store"] == 0
    assert sync_plans(path, file, commit=True)["stored"] == 0
    data = json.loads(file.read_text(encoding="utf-8"))
    next(item for item in data if item["plan_id"] == CS_PLAN)["notes"] = draft.notes + " Edited draft."
    file.write_text(json.dumps(data), encoding="utf-8")
    assert sync_plans(path, file, commit=True)["stored"] == 1


@pytest.mark.parametrize("document,expected", [
    ("[]", None),
    ("null", None),
    ("1", None),  # the JSON column has NUMERIC affinity: this comes back as an int
    ('"double-encoded"', None),
    ("{}", RecordedProvenance(None, None, None)),
    ('{"source_html_sha256": 123, "review_status": "source_checked"}', RecordedProvenance("123", "source_checked", None)),
    ('{"source_html_sha256": "%s", "review_status": "source_checked", "captured_on": "not-a-date"}' % ("a" * 64),
     RecordedProvenance("a" * 64, "source_checked", None)),
    ('{"source_html_sha256": "%s", "review_status": "source_checked", "captured_on": "2026-10-03T00:00:00"}' % ("b" * 64),
     RecordedProvenance("b" * 64, "source_checked", date(2026, 10, 3))),
])
def test_stored_rows_of_any_shape_are_read_without_crashing(runtime, document, expected):
    path, file = runtime
    sync_plans(path, file, commit=True)
    conn = connect(path)
    conn.execute("UPDATE program_plans SET document=? WHERE plan_id=?", (document, CS_PLAN))
    conn.commit()
    assert ProgramPlanRepository(conn).recorded(CS_PLAN) == expected
    conn.close()
    if expected is not None and expected.source_html_sha256:
        with pytest.raises(PlanDowngradeError, match="drops_source_fingerprint"):
            sync_plans(path, file)
    else:
        assert sync_plans(path, file)["would_store"] == 1


def test_dry_run_and_commit_judge_a_tampered_row_alike(runtime):
    """Slots are judged by the row columns; a scope written inside the document does not hide it."""
    path, file = runtime
    sync_plans(path, file, commit=True)
    fingerprint_stored_plan(path, CS_PLAN)
    conn = connect(path)
    conn.execute("UPDATE program_plans SET document=json_set(document, '$.campus', 'seattle') WHERE plan_id=?", (CS_PLAN,))
    conn.commit()
    conn.close()
    before = stored_documents(path)
    for commit in [False, True]:
        with pytest.raises(PlanDowngradeError) as refused:
            sync_plans(path, file, commit=commit)
        assert refused.value.downgrades == [{"plan_id": CS_PLAN, "reason": "drops_source_fingerprint"}]
        assert stored_documents(path) == before


def test_sync_respects_what_a_corrupt_fingerprinted_row_records(runtime):
    path, file = runtime
    sync_plans(path, file, commit=True)
    fingerprint_stored_plan(path, CS_PLAN)
    conn = connect(path)
    conn.execute("UPDATE program_plans SET content_hash=? WHERE plan_id=?", ("0" * 64, CS_PLAN))
    conn.commit()
    conn.close()
    before = stored_documents(path)
    for commit in [False, True]:
        with pytest.raises(PlanDowngradeError) as refused:
            sync_plans(path, file, commit=commit)
        assert refused.value.downgrades == [{"plan_id": CS_PLAN, "reason": "drops_source_fingerprint"}]
        assert stored_documents(path) == before
    assert sync_plans(path, file, commit=True, allow_downgrade=True)["stored"] == 1


def test_rebinding_a_fingerprinted_plan_id_still_reports_the_scope_error(runtime):
    path, file = runtime
    sync_plans(path, file, commit=True)
    fingerprint_stored_plan(path, CS_PLAN)
    data = [item for item in json.loads(file.read_text(encoding="utf-8")) if item["plan_id"] == CS_PLAN]
    data[0]["campus"] = "seattle"
    file.write_text(json.dumps(data), encoding="utf-8")
    for commit in [False, True]:
        with pytest.raises(ValueError, match="rebound"):
            sync_plans(path, file, commit=commit)


def test_cli_keeps_stdout_json_when_a_stored_row_is_unusable(runtime):
    path, file = runtime
    sync_plans(path, file, commit=True)
    conn = connect(path)
    conn.execute("UPDATE program_plans SET content_hash=? WHERE plan_id=?", ("0" * 64, CS_PLAN))
    conn.commit()
    conn.close()
    command = [sys.executable, str(ROOT / "scripts/sync_program_plans.py"), "--db-path", str(path), "--plan-file", str(file)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["would_store"] == 1
    assert "program.plan_unusable" in result.stderr


def test_cli_refuses_a_downgrade_with_the_reason_then_honours_allow_downgrade(runtime):
    path, file = runtime
    sync_plans(path, file, commit=True)
    fingerprint_stored_plan(path, CS_PLAN)
    before = stored_documents(path)
    command = [sys.executable, str(ROOT / "scripts/sync_program_plans.py"), "--db-path", str(path),
               "--plan-file", str(file), "--commit"]
    refused = subprocess.run(command, capture_output=True, text=True, timeout=45)
    assert refused.returncode == 1
    assert f"{CS_PLAN} (drops_source_fingerprint)" in refused.stdout and "--allow-downgrade" in refused.stdout
    assert "nothing was written" in refused.stdout
    assert stored_documents(path) == before
    allowed = subprocess.run([*command, "--allow-downgrade"], capture_output=True, text=True, timeout=45)
    assert allowed.returncode == 0, allowed.stdout + allowed.stderr
    assert json.loads(allowed.stdout)["stored"] == 1


def test_persisted_05a_hash_remains_readable_and_idempotent(empty_db):
    """Construct the exact old schema shape/hash, not the new hash helper."""
    raw = json.loads(SOURCE.read_text(encoding="utf-8"))[0]
    plan = ProgramPlan.model_validate(raw)
    old_document = plan.model_dump(mode="json")
    old_document.pop("source_html_sha256")
    stack = [old_document["requirements"]]
    while stack:
        node = stack.pop()
        for key in ["subject_codes", "course_ranges", "excluded_course_codes", "activate_when"]:
            node.pop(key)
        stack.extend(node["children"])
    old_hash = hashlib.sha256(json.dumps(old_document, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    ProgramRepository(empty_db).add_program(Program(program_id="cs-ms", full_name="Old family", prefix="CS"))
    payload = json.dumps(old_document)
    empty_db.execute("INSERT INTO program_plans VALUES(?,?,?,?,?,?,?,?)",
        (plan.plan_id, *plan.scope_key(), payload, old_hash))
    repo = ProgramPlanRepository(empty_db)
    assert repo.list_for_program("cs-ms") == [plan]
    assert repo.store(plan) is False
    assert empty_db.execute("SELECT document FROM program_plans").fetchone()[0] == payload
