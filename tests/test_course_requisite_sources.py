"""Immutable course inputs and no-write reports; no real HTTP/DB in tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from schemas.course_requisite_source import CourseRequisiteSource, verify_course_source
from scripts.audit_course_requisites import build_report
from scripts.capture_course_requisites import capture_departments

ROOT = Path(__file__).resolve().parent.parent
URL = "https://catalog.northeastern.edu/course-descriptions/cs/"


def source_html(prereq="(CS 5001 with a minimum grade of C- or CS 5010 with a minimum grade of B-); CS 5002", *, duplicate=False):
    block = f'''<div class="courseblock"><p class="courseblocktitle">CS 5004. Design. (4 Hours)</p>
<p class="cb_desc">Approval outside requisite clauses is not evaluated.</p>
<p class="courseblockextra"><strong>Prerequisite(s): </strong>{prereq}</p>
<p class="courseblockextra"><strong>Corequisite(s): </strong>CS 5005</p></div>'''
    return ('<h1>Computer Science (CS)</h1><p>2026-2027 Edition</p>' + block * (2 if duplicate else 1)).encode()


def mock_client(content=None, *, status=200, headers=None):
    return httpx.Client(transport=httpx.MockTransport(lambda request:
        httpx.Response(status, content=content if content is not None else source_html(), headers=headers or {"content-type": "text/html; charset=utf-8"})))


def archive(tmp_path, content=None):
    directory = tmp_path / "inputs"
    with mock_client(content) as client:
        captured = capture_departments(["cs"], "2026-2027", directory, client=client)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(captured), encoding="utf-8")
    return manifest, directory, CourseRequisiteSource.model_validate(captured[0])


def test_capture_repetition_deduplicates_departments_and_preserves_bytes_timestamp(tmp_path):
    with mock_client() as client:
        first = capture_departments(["cs", "cs"], "2026-2027", tmp_path, client=client)
        before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
        assert capture_departments(["cs"], "2026-2027", tmp_path, client=client) == first
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before
    assert len(before) == 2
    source = CourseRequisiteSource.model_validate(first[0])
    assert verify_course_source(source, tmp_path) == source_html()


@pytest.mark.parametrize("departments,year", [([], "2026-2027"), (["CS"], "2026-2027"), (["../cs"], "2026-2027"), (["cs"], "2026-2028")])
def test_bad_capture_scope_fails_before_network_or_output(tmp_path, departments, year):
    def no_request(request):
        pytest.fail("Invalid scope reached network")
    with httpx.Client(transport=httpx.MockTransport(no_request)) as client:
        with pytest.raises(ValueError):
            capture_departments(departments, year, tmp_path / "absent", client=client)
    assert not (tmp_path / "absent").exists()


@pytest.mark.parametrize("kind", ["redirect", "error", "not-html", "wrong-year", "wrong-dept", "oversize", "no-blocks"])
def test_capture_refuses_changed_or_unbounded_page_without_writing(tmp_path, kind):
    content, status, headers = source_html(), 200, {"content-type": "text/html"}
    if kind == "redirect":
        status, headers = 302, {"location": "https://evil.test/", "content-type": "text/html"}
    elif kind == "error":
        status = 404
    elif kind == "not-html":
        headers = {"content-type": "application/json"}
    elif kind == "wrong-year":
        content = content.replace(b"2026-2027", b"2025-2026")
    elif kind == "wrong-dept":
        content = content.replace(b"(CS)", b"(DS)")
    elif kind == "oversize":
        content = b"x" * 2_000_001
    else:
        content = b"<h1>Computer Science (CS)</h1><p>2026-2027 Edition</p>"
    with mock_client(content, status=status, headers=headers) as client:
        with pytest.raises((ValueError, httpx.HTTPError)):
            capture_departments(["cs"], "2026-2027", tmp_path / "absent", client=client)
    assert not (tmp_path / "absent").exists()


def test_existing_capture_metadata_conflict_is_not_overwritten(tmp_path):
    manifest, directory, source = archive(tmp_path)
    sidecar = directory / f"{source.sha256}.json"
    conflicting = source.model_dump(mode="json")
    conflicting["byte_count"] += 1
    sidecar.write_text(json.dumps(conflicting), encoding="utf-8")
    before = sidecar.read_bytes()
    with mock_client() as client, pytest.raises(ValueError, match="conflict"):
        capture_departments(["cs"], "2026-2027", directory, client=client)
    assert sidecar.read_bytes() == before


@pytest.mark.parametrize("kind", ["html", "sidecar", "manifest-time", "missing", "oversize-sidecar"])
def test_report_refuses_bad_fixed_inputs_before_returning_partial_records(tmp_path, kind):
    manifest, directory, source = archive(tmp_path)
    if kind == "html":
        (directory / f"{source.sha256}.html").write_bytes(b"changed")
    elif kind == "sidecar":
        (directory / f"{source.sha256}.json").write_text("not-json")
    elif kind == "missing":
        directory = tmp_path / "missing"
    elif kind == "oversize-sidecar":
        (directory / f"{source.sha256}.json").write_text("x" * 16_001)
    else:
        data = json.loads(manifest.read_text())
        data[0]["captured_at"] = "2026-10-02T00:00:00Z"
        manifest.write_text(json.dumps(data))
    with pytest.raises((ValueError, OSError)):
        build_report(manifest, directory, ["CS 5004"])


def test_report_is_readonly_explicitly_unscoped_and_keeps_corequisite_separate(tmp_path):
    manifest, directory, source = archive(tmp_path)
    before = {path.name: path.read_bytes() for path in directory.iterdir()}
    report = build_report(manifest, directory, ["cs5004"])
    record = report["records"][0]
    assert report["unparsed_sections"] == 0 and record["campus"] is None
    assert record["source_html_sha256"] == source.sha256 and record["catalog_year"] == "2026-2027"
    assert record["requisites"]["prerequisite"]["rule"]["kind"] == "all_of"
    assert record["requisites"]["corequisite"]["rule"]["course_code"] == "CS 5005"
    assert "campus_and_personal_pathway_not_declared" in record["warnings"]
    assert {path.name: path.read_bytes() for path in directory.iterdir()} == before


@pytest.mark.parametrize("requested", [[], ["CS 9999"], ["CS 5004", "cs5004"], ["../cs"], ["CS 5004"] * 101])
def test_report_never_silently_drops_missing_invalid_or_duplicate_requested_courses(tmp_path, requested):
    manifest, directory, _ = archive(tmp_path)
    with pytest.raises(ValueError):
        build_report(manifest, directory, requested)


def test_duplicate_selected_blocks_are_ambiguous_not_first_match(tmp_path):
    manifest, directory, _ = archive(tmp_path, source_html(duplicate=True))
    with pytest.raises(ValueError, match="duplicate"):
        build_report(manifest, directory, ["CS 5004"])


def test_self_reference_is_preserved_with_explicit_warning(tmp_path):
    manifest, directory, _ = archive(tmp_path, source_html("CS 5004"))
    record = build_report(manifest, directory, ["CS 5004"])["records"][0]
    assert record["requisites"]["prerequisite"]["rule"]["course_code"] == "CS 5004"
    assert "self_reference_preserved_not_auto_corrected" in record["warnings"]


@pytest.mark.parametrize("partial", [False, True])
def test_real_report_cli_stdout_and_exit_status_do_not_write_files_or_database(tmp_path, partial):
    manifest, directory, _ = archive(tmp_path, source_html("CS 5001 or permission of instructor") if partial else None)
    before = {str(path.relative_to(tmp_path)): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    command = [sys.executable, str(ROOT / "scripts/audit_course_requisites.py"), "--manifest-file", str(manifest),
               "--source-dir", str(directory), "--course-code", "CS 5004"]
    result = subprocess.run(command, capture_output=True, text=True, timeout=45)
    assert result.returncode == (2 if partial else 0), result.stderr
    report = json.loads(result.stdout)
    assert report["unparsed_sections"] == (1 if partial else 0)
    if partial:
        assert report["records"][0]["requisites"]["prerequisite"]["rule"] is None
    assert {str(path.relative_to(tmp_path)): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == before


@pytest.mark.parametrize("url", ["http://catalog.northeastern.edu/course-descriptions/cs/", "https://catalog.northeastern.edu.evil.test/course-descriptions/cs/",
    "https://catalog.northeastern.edu/course-descriptions/cs/?q=evil", "https://catalog.northeastern.edu/graduate/test/"])
def test_course_source_url_is_not_program_scope_or_arbitrary_link(tmp_path, url):
    manifest, _, _ = archive(tmp_path)
    data = json.loads(manifest.read_text())[0]
    data["url"] = url
    with pytest.raises(ValueError):
        CourseRequisiteSource.model_validate(data)


def test_public_course_manifest_is_three_department_inputs_not_boston_eligibility():
    data = json.loads((ROOT / "data/course_requisite_sources/catalog_2026_2027_manifest.json").read_text(encoding="utf-8"))
    metadata = [CourseRequisiteSource.model_validate(item) for item in data]
    assert {item.url.rsplit("/", 2)[1] for item in metadata} == {"cs", "ds", "info"}
    assert all(item.catalog_year == "2026-2027" and item.captured_at.tzinfo for item in metadata)
    assert all("campus" not in item.model_dump() for item in metadata)


@pytest.mark.parametrize("kind", ["duplicate-url", "mixed-edition", "empty"])
def test_report_rejects_mixed_or_duplicate_manifest_identity(tmp_path, kind):
    manifest, directory, _ = archive(tmp_path)
    data = json.loads(manifest.read_text())
    if kind == "empty":
        data = []
    else:
        other = dict(data[0])
        if kind == "mixed-edition":
            other.update(url="https://catalog.northeastern.edu/course-descriptions/ds/", catalog_year="2025-2026", page_title="Data Science (DS)")
        data.append(other)
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        build_report(manifest, directory, ["CS 5004"])


def test_real_report_cli_bad_inputs_exit_one_without_partial_json_stdout(tmp_path):
    manifest, directory, _ = archive(tmp_path)
    command = [sys.executable, str(ROOT / "scripts/audit_course_requisites.py"), "--manifest-file", str(manifest),
               "--source-dir", str(directory), "--course-code", "CS 5004", "--course-code", "CS 9999"]
    result = subprocess.run(command, capture_output=True, text=True, timeout=45)
    assert result.returncode == 1 and result.stdout == "" and "no DB or files changed" in result.stderr
