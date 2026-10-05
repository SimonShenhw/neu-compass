"""Frozen input checks and mocked capture; real CLI uses only temporary files."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from db.connection import connect
from db.program_plan_repository import PlanDowngradeError
from db.program_repository import ProgramRepository
from schemas.program import Program
from schemas.program_plan import ProgramPlan
from schemas.program_source import MAX_HTML_BYTES, SourceCapture, inspect_html, verify_archived_source
from scripts.capture_program_sources import capture_sources
from scripts.init_db import init_database
from scripts.sync_program_plans import sync_plans
from scripts.audit_program_rule_sources import audit_plan, credit_groups, subject_pool, tables_by_heading

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "data/program_plan_seed/boston_2026_2027_core_fragments.json"
EXTENDED = ROOT / "data/program_plan_seed/boston_2026_2027_extended_rules.json"


def html_for(plan, *, edition=None, title=None):
    page_title = title or plan.source_title.removesuffix(f", {plan.catalog_year} Edition")
    return f"<html><h1>{page_title}</h1><p>{edition or plan.catalog_year} Edition</p></html>".encode()


def archived_plan(tmp_path, item=None, content=None):
    data = dict(item or json.loads(CORE.read_text())[0])
    plan = ProgramPlan.model_validate(data)
    content = content or html_for(plan)
    digest = hashlib.sha256(content).hexdigest()
    data["source_html_sha256"] = digest
    plan = ProgramPlan.model_validate(data)
    archive = tmp_path / "sources"
    archive.mkdir(exist_ok=True)
    metadata = SourceCapture(url=plan.source_url, catalog_year=plan.catalog_year,
        captured_at=datetime(2026, 10, 1, tzinfo=timezone.utc), sha256=digest,
        byte_count=len(content), page_title=plan.source_title.removesuffix(", 2026-2027 Edition"))
    (archive / f"{digest}.html").write_bytes(content)
    (archive / f"{digest}.json").write_text(metadata.model_dump_json(), encoding="utf-8")
    return plan, archive


def test_source_capture_metadata_and_html_validate_offline(tmp_path):
    plan, archive = archived_plan(tmp_path)
    metadata = verify_archived_source(plan, archive)
    assert metadata.sha256 == plan.source_html_sha256


@pytest.mark.parametrize("change", ["html", "url", "year", "date", "size", "title", "hash", "missing"])
def test_tampered_or_missing_archive_is_rejected(tmp_path, change):
    plan, archive = archived_plan(tmp_path)
    path = archive / f"{plan.source_html_sha256}.json"
    data = json.loads(path.read_text())
    if change == "html":
        (archive / f"{plan.source_html_sha256}.html").write_bytes(b"different")
    elif change == "missing":
        path.unlink()
    else:
        key, value = {"url": ("url", "https://catalog.northeastern.edu/graduate/other/"),
                      "year": ("catalog_year", "2025-2026"), "date": ("captured_at", "2026-09-30T00:00:00Z"),
                      "size": ("byte_count", 1), "title": ("page_title", "Wrong title"),
                      "hash": ("sha256", "0" * 64)}[change]
        data[key] = value
        path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises((ValueError, FileNotFoundError)):
        verify_archived_source(plan, archive)


@pytest.mark.parametrize("kind", ["wrong-edition", "wrong-title", "empty", "oversized"])
def test_capture_inspection_refuses_wrong_or_unbounded_input(kind):
    plan = ProgramPlan.model_validate(json.loads(CORE.read_text())[0])
    content = {"wrong-edition": html_for(plan, edition="2025-2026"),
               "wrong-title": html_for(plan, title="Another program"), "empty": b"",
               "oversized": b"X" * (MAX_HTML_BYTES + 1)}[kind]
    with pytest.raises(ValueError):
        inspect_html(content, plan)


def test_capture_is_immutable_and_deduplicates_shared_source_urls(tmp_path):
    data = json.loads(CORE.read_text())
    file = tmp_path / "plans.json"
    file.write_text(json.dumps([*data, data[1]]))
    by_url = {item["source_url"]: ProgramPlan.model_validate(item) for item in data}
    requests = []
    def handle(request):
        requests.append(str(request.url))
        return httpx.Response(200, content=html_for(by_url[str(request.url)]), headers={"content-type": "text/html; charset=utf-8"})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        archive = tmp_path / "archive"
        first = capture_sources(file, archive, client=client)
        before = {path.name: path.read_bytes() for path in archive.iterdir()}
        second = capture_sources(file, archive, client=client)
    assert first == second and len(first) == 3 and len(requests) == 6
    assert {path.name: path.read_bytes() for path in archive.iterdir()} == before


@pytest.mark.parametrize("kind", ["redirect", "json", "oversized", "wrong-edition", "404"])
def test_bad_capture_does_not_follow_redirect_or_write_invalid_input(tmp_path, kind):
    data = json.loads(CORE.read_text())[:1]
    plan = ProgramPlan.model_validate(data[0])
    file = tmp_path / "plans.json"
    file.write_text(json.dumps(data))
    requests = []
    def handle(request):
        requests.append(str(request.url))
        if kind == "redirect":
            return httpx.Response(302, headers={"location": "https://evil.test/"})
        if kind == "404":
            return httpx.Response(404)
        content = html_for(plan, edition="2025-2026") if kind == "wrong-edition" else html_for(plan)
        if kind == "oversized":
            content = b"X" * (MAX_HTML_BYTES + 1)
        return httpx.Response(200, content=content, headers={"content-type": "application/json" if kind == "json" else "text/html"})
    archive = tmp_path / "archive"
    with httpx.Client(transport=httpx.MockTransport(handle)) as client, pytest.raises((ValueError, httpx.HTTPError)):
        capture_sources(file, archive, client=client)
    assert requests == [plan.source_url] and not archive.exists()


def test_existing_conflicting_capture_metadata_is_preserved(tmp_path):
    data = json.loads(CORE.read_text())[:1]
    plan = ProgramPlan.model_validate(data[0])
    file = tmp_path / "plans.json"
    file.write_text(json.dumps(data))
    archive = tmp_path / "archive"
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=html_for(plan), headers={"content-type": "text/html"}))) as client:
        metadata = capture_sources(file, archive, client=client)[0]
        path = archive / f"{metadata['sha256']}.json"
        metadata["url"] = "https://catalog.northeastern.edu/graduate/other/"
        path.write_text(json.dumps(metadata))
        before = path.read_bytes()
        with pytest.raises(ValueError, match="conflict"):
            capture_sources(file, archive, client=client)
        assert path.read_bytes() == before


def test_source_timestamp_requires_timezone(tmp_path):
    plan, archive = archived_plan(tmp_path)
    data = json.loads((archive / f"{plan.source_html_sha256}.json").read_text())
    data["captured_at"] = "2026-10-01T12:00:00"
    with pytest.raises(ValueError, match="timezone"):
        SourceCapture.model_validate(data)


@pytest.mark.parametrize("commit", [False, True])
def test_fingerprinted_import_requires_archives_before_any_db_change(tmp_path, commit):
    path = tmp_path / "runtime.db"
    init_database(path)
    file = tmp_path / "plans.json"
    plan, archive = archived_plan(tmp_path)
    file.write_text(json.dumps([plan.model_dump(mode="json")]))
    before = path.read_bytes()
    with pytest.raises(ValueError, match="explicit"):
        sync_plans(path, file, commit=commit)
    assert path.read_bytes() == before
    (archive / f"{plan.source_html_sha256}.html").write_bytes(b"tampered")
    with pytest.raises(ValueError):
        sync_plans(path, file, commit=commit, source_dir=archive)
    assert path.read_bytes() == before


def test_extended_bundle_real_cli_import_on_temp_db_is_readonly_then_idempotent(tmp_path):
    path, file = tmp_path / "runtime.db", tmp_path / "plans.json"
    init_database(path)
    conn = connect(path)
    for family in ["cs-ms", "ds-ms", "info-ms"]:
        ProgramRepository(conn).add_program(Program(program_id=family, full_name="Legacy", prefix=family.split("-")[0].upper()))
    conn.commit()
    old_rows = [tuple(row) for row in conn.execute("SELECT * FROM programs ORDER BY program_id")]
    conn.close()
    plans, archive = [], None
    for item in json.loads(EXTENDED.read_text()):
        plan, archive = archived_plan(tmp_path, item)
        plans.append(plan.model_dump(mode="json"))
    file.write_text(json.dumps(plans))
    command = [sys.executable, str(ROOT / "scripts/sync_program_plans.py"), "--db-path", str(path),
               "--plan-file", str(file), "--source-dir", str(archive)]
    before = path.read_bytes()
    for extra, expected in [([], 0), (["--commit"], 5), (["--commit"], 0)]:
        result = subprocess.run([*command, *extra], capture_output=True, text=True, timeout=45)
        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads(result.stdout)["stored"] == expected
        if not extra:
            assert path.read_bytes() == before
    conn = connect(path)
    assert conn.execute("SELECT COUNT(*) FROM program_plans").fetchone()[0] == 5
    assert [tuple(row) for row in conn.execute("SELECT * FROM programs ORDER BY program_id")] == old_rows
    conn.close()


def test_rerunning_the_core_layer_after_extended_is_refused(tmp_path):
    """The release imports core, then extended (re-using two core plan IDs, now
    fingerprinted). Re-running core alone used to downgrade those two silently."""
    path = tmp_path / "runtime.db"
    init_database(path)
    conn = connect(path)
    for family in ["cs-ms", "ds-ms", "info-ms"]:
        ProgramRepository(conn).add_program(Program(program_id=family, full_name="Legacy", prefix=family.split("-")[0].upper()))
    conn.commit()
    conn.close()
    core_file, extended_file = tmp_path / "core.json", tmp_path / "extended.json"
    core_file.write_text(CORE.read_text(encoding="utf-8"), encoding="utf-8")
    plans, archive = [], None
    for item in json.loads(EXTENDED.read_text(encoding="utf-8")):
        plan, archive = archived_plan(tmp_path, item)
        plans.append(plan.model_dump(mode="json"))
    extended_file.write_text(json.dumps(plans), encoding="utf-8")

    def documents():
        conn = connect(path)
        try:
            return [tuple(row) for row in conn.execute(
                "SELECT plan_id, document, content_hash FROM program_plans ORDER BY plan_id")]
        finally:
            conn.close()

    assert sync_plans(path, core_file, commit=True)["stored"] == 3
    assert sync_plans(path, extended_file, commit=True, source_dir=archive)["stored"] == 5
    imported = documents()
    shared = ["cs-ms-boston-2026-2027-standard", "info-ms-boston-2026-2027-standard-general"]
    for commit in [False, True]:
        with pytest.raises(PlanDowngradeError) as refused:
            sync_plans(path, core_file, commit=commit)
        assert sorted(item["plan_id"] for item in refused.value.downgrades) == shared
        assert {item["reason"] for item in refused.value.downgrades} == {"drops_source_fingerprint"}
        assert documents() == imported
    assert sync_plans(path, extended_file, commit=True, source_dir=archive)["stored"] == 0


def test_table_parser_preserves_group_boundaries_and_stops_before_optional_coop():
    rows = ["Complete 8 semester hours from the following: 8", "ARTG 5150 Title", "ARTG 5151 Title",
            "Complete 8 semester hours from the following: 8", "CS 5340 Title", "Optional Co-op", "EEAM 6964 Work"]
    assert credit_groups(rows) == [(8, ["ARTG 5150", "ARTG 5151"]), (8, ["CS 5340"])]
    assert credit_groups(["INFO 7945 Project", "Complete 12 semester hours from restricted 12"], allow_leading_courses=True) == [(12, [])]
    with pytest.raises(ValueError, match="Unattached"):
        credit_groups(["CS 5340 Course"])


def test_source_subject_parser_separates_exceptions_and_finite_courses():
    assert subject_pool(["INFO (except INFO 5200)", "DAMG", "MUST 5510 Sound"]) == ({"INFO", "DAMG"}, {"MUST 5510"}, {"INFO 5200"})


def test_source_table_parser_rejects_ambiguous_headings():
    content = b'<h2>A</h2><table class="sc_courselist"><tr><td>CS 5800</td></tr></table><h2>A</h2><table class="sc_courselist"></table>'
    with pytest.raises(ValueError, match="Ambiguous"):
        tables_by_heading(content)


@pytest.mark.parametrize("tamper", [None, "credits", "exclusion", "project"])
def test_info_source_audit_checks_branch_amounts_courses_and_exclusions(tmp_path, tamper):
    """Independent small synthetic table, not a copy of the official page."""
    source = '<h1>Information Systems, MSIS (Boston)</h1><p>2026-2027 Edition</p>'
    for heading, rows in [
        ("Coursework Option", ["Complete 16 semester hours from restricted 16", "Complete 12 semester hours from other 12"]),
        ("Project Option", ["INFO 7945 Project 4", "Complete 12 semester hours from restricted 12", "Complete 12 semester hours from other 12"]),
        ("Thesis Option", ["INFO 7945 Project 4", "INFO 7990 Thesis 4", "Complete 8 semester hours from restricted 8", "Complete 12 semester hours from other 12"]),
        ("Restricted Electives Course List", ["INFO (except INFO 5200)"]),
        ("Other Electives Course List", ["CSYE (except CSYE 6220)", "DAMG", "INFO (except INFO 5200)", "MUST 5510 Sound", "MUST 5520 Sound", "MUST 6603 Sound", "TELE"]),
    ]:
        source += f'<h3>{heading}</h3><table class="sc_courselist">' + ''.join(f'<tr><td>{row}</td></tr>' for row in rows) + '</table>'
    data = json.loads(EXTENDED.read_text())[-1]
    plan, archive = archived_plan(tmp_path, data, source.encode())
    assert len(audit_plan(plan, archive)["checks"]) == 2
    if tamper is None:
        return
    data = plan.model_dump(mode="json")
    branches = data["requirements"]["children"][1]["children"]
    if tamper == "credits":
        branches[0]["children"][0]["min_credits"] = 12
    elif tamper == "exclusion":
        branches[0]["children"][1]["excluded_course_codes"] = ["INFO 5200"]
    else:
        branches[1]["children"][0]["course_code"] = "INFO 7990"
    with pytest.raises(ValueError, match="mismatch"):
        audit_plan(ProgramPlan.model_validate(data), archive)
