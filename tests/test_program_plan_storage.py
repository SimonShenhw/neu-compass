"""Actual isolated SQLite/CLI sync; preserves legacy and Course columns."""

from __future__ import annotations

import json
import hashlib
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from db.connection import connect
from db.program_plan_repository import ProgramPlanRepository
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
