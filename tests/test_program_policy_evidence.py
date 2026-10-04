"""Policy bytes and exact plan scope are evidence, not an eligibility verdict."""

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from db.program_plan_repository import content_hash
from schemas.program_plan import ProgramPlan
from schemas.program_policy import (PolicyEvidence, PolicySourceRequest, ProgramPolicyBundle,
    paragraph_hash, policy_paragraphs, verify_home_college, verify_policy_source)
from schemas.program_source import SourceCapture
from scripts.audit_program_policy_sources import audit_bundle
from scripts.capture_program_policy_sources import capture_policy_sources

ROOT = Path(__file__).resolve().parent.parent
SEEDS = ROOT / "data/program_policy_seed"


def request_data():
    return dict(authority="khoury", catalog_year="2026-2027",
        url="https://catalog.northeastern.edu/graduate/computer-information-science/academic-policies-procedures/academic-probation-and-dismissal/",
        page_title="Academic Probation and Dismissal")


def html(*, year="2026-2027", title="Academic Probation and Dismissal", body=None):
    body = body or '<h2>Standing</h2><p>Independent synthetic policy paragraph.</p>'
    return (f'<html><h1>{title}</h1><p>{year} Edition</p>'
        f'<div id="textcontainer">{body}</div></html>').encode()


@pytest.mark.parametrize("key,value", [
    ("url", "http://catalog.northeastern.edu/graduate/academic-policies-procedures/minimum-gpa/"),
    ("url", "https://evil.test/graduate/academic-policies-procedures/minimum-gpa/"),
    ("url", "https://catalog.northeastern.edu/graduate/engineering/academic-policies-procedures/course-selection/"),
    ("url", "https://catalog.northeastern.edu/graduate/computer-information-science/"),
    ("catalog_year", "2026-2028"), ("page_title", " "), ("authority", "guess"),
])
def test_requests_reject_nonofficial_or_wrong_authority(key, value):
    data = request_data()
    data[key] = value
    with pytest.raises(ValidationError):
        PolicySourceRequest.model_validate(data)


def test_archive_edition_must_match():
    data = request_data()
    data["url"] = data["url"].replace("/graduate/", "/archive/2025-2026/graduate/")
    with pytest.raises(ValidationError):
        PolicySourceRequest.model_validate(data)


def test_paragraphs_are_only_inside_unique_policy_body():
    content = html(body='<h2>Standing</h2><p>A\u00a0 B <a>source</a>.</p><h3>Appeals</h3><p>Not an automatic decision.</p>')
    assert policy_paragraphs(content) == [("Standing", "A B source ."), ("Appeals", "Not an automatic decision.")]
    with pytest.raises(ValueError):
        policy_paragraphs(content.replace(b'id="textcontainer"', b'id="other"'))
    with pytest.raises(ValueError):
        policy_paragraphs(content.replace(b'</html>', b'<div id="textcontainer"><p>duplicate</p></div></html>'))


def test_capture_preserves_original_timestamp_and_bytes(tmp_path):
    file = tmp_path / "requests.json"
    file.write_text(json.dumps([request_data(), request_data()]))
    archive = tmp_path / "archive"
    calls = []
    def handle(request):
        calls.append(str(request.url))
        return httpx.Response(200, content=html(), headers={"content-type": "text/html"})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        first = capture_policy_sources(file, archive, client=client)
        before = {path.name: path.read_bytes() for path in archive.iterdir()}
        second = capture_policy_sources(file, archive, client=client)
    assert first == second and len(first) == 1 and len(calls) == 2
    assert {path.name: path.read_bytes() for path in archive.iterdir()} == before
    assert first[0]["sha256"] == hashlib.sha256(html()).hexdigest()


@pytest.mark.parametrize("kind", ["redirect", "json", "404", "edition", "title", "empty", "body", "oversized"])
def test_invalid_capture_never_writes_or_follows_redirect(tmp_path, kind):
    file = tmp_path / "requests.json"
    file.write_text(json.dumps([request_data()]))
    archive = tmp_path / "archive"
    calls = []
    def handle(request):
        calls.append(str(request.url))
        if kind == "redirect":
            return httpx.Response(302, headers={"location": "https://evil.test/"})
        if kind == "404":
            return httpx.Response(404)
        content = {"edition": html(year="2025-2026"), "title": html(title="Another page"),
            "empty": b"", "body": b'<h1>Academic Probation and Dismissal</h1><p>2026-2027 Edition</p>',
            "oversized": b"x" * 2_000_001}.get(kind, html())
        return httpx.Response(200, content=content, headers={"content-type": "application/json" if kind == "json" else "text/html"})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client, pytest.raises((ValueError, httpx.HTTPError)):
        capture_policy_sources(file, archive, client=client)
    assert len(calls) == 1 and not archive.exists()


def fixture_bundle(tmp_path):
    """Independent synthetic policy and program archives, no runtime DB/network."""
    policy_dir, program_dir = tmp_path / "policy", tmp_path / "program"
    policy_dir.mkdir()
    program_dir.mkdir()
    content = html()
    source = SourceCapture(url=request_data()["url"], catalog_year="2026-2027",
        captured_at=datetime(2026, 10, 2, 10, tzinfo=timezone.utc), sha256=hashlib.sha256(content).hexdigest(),
        byte_count=len(content), page_title=request_data()["page_title"])
    (policy_dir / f"{source.sha256}.html").write_bytes(content)
    (policy_dir / f"{source.sha256}.json").write_text(source.model_dump_json())
    data = json.loads((ROOT / "data/program_plan_seed/boston_2026_2027_extended_rules.json").read_text())[0]
    program_content = (f'<h1>Computer Science, MSCS (Boston)</h1><p>2026-2027 Edition</p>'
        '<nav id="breadcrumb"><a href="/graduate/computer-information-science/">'
        'Khoury College of Computer Sciences</a></nav>').encode()
    data["source_html_sha256"] = hashlib.sha256(program_content).hexdigest()
    plan = ProgramPlan.model_validate(data)
    program_meta = SourceCapture(url=plan.source_url, catalog_year=plan.catalog_year,
        captured_at=datetime(2026, 10, 1, tzinfo=timezone.utc), sha256=plan.source_html_sha256,
        byte_count=len(program_content), page_title="Computer Science, MSCS (Boston)")
    (program_dir / f"{program_meta.sha256}.html").write_bytes(program_content)
    (program_dir / f"{program_meta.sha256}.json").write_text(program_meta.model_dump_json())
    bundle_data = dict(checked_by="synthetic-reviewer", checked_on="2026-10-02",
        policies=[dict(policy_id="standing", authority="khoury", source=source.model_dump(mode="json"),
            fragments=[dict(fragment_id="standing-evidence", paragraph_index=0, heading="Standing",
                paragraph_sha256=paragraph_hash("Independent synthetic policy paragraph."),
                summary="Synthetic paraphrase; not an eligibility rule.", limitation="Incomplete policy evidence.")])],
        links=[dict(plan_id=plan.plan_id, program_id=plan.program_id, campus=plan.campus,
            catalog_year=plan.catalog_year, pathway=plan.pathway, concentration=plan.concentration,
            plan_content_sha256=content_hash(plan), home_college="khoury", policy_ids=["standing"])])
    bundle_file, plan_file = tmp_path / "bundle.json", tmp_path / "plans.json"
    bundle_file.write_text(json.dumps(bundle_data))
    plan_file.write_text(json.dumps([plan.model_dump(mode="json")]))
    return bundle_data, bundle_file, plan_file, policy_dir, program_dir


def test_audit_keeps_policy_and_course_grades_separate_and_has_no_verdict(tmp_path):
    _, bundle_file, plan_file, policy_dir, program_dir = fixture_bundle(tmp_path)
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    report = audit_bundle(bundle_file, [plan_file], policy_dir, program_dir)
    assert report["coverage"] == "selected_fragments_only"
    assert report["links"][0]["concentration"] is None
    assert report["policies"][0]["fragments"][0]["source_paragraph"] == "Independent synthetic policy paragraph."
    assert "university_and_college_rules_not_merged" in report["warnings"]
    assert not {"eligible", "passed", "graduation_ready", "combined_gpa"}.intersection(report)
    assert {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("kind", ["college", "year", "unknown-reference", "duplicate-policy", "duplicate-link",
    "duplicate-fragment", "duplicate-position", "complete", "review-date", "blank-summary", "blank-reviewer", "unused-policy"])
def test_bundle_rejects_misleading_or_ambiguous_evidence(tmp_path, kind):
    data, *_ = fixture_bundle(tmp_path)
    policy, link = data["policies"][0], data["links"][0]
    if kind == "college":
        link["home_college"] = "engineering"
    elif kind == "year":
        link["catalog_year"] = "2025-2026"
    elif kind == "unknown-reference":
        link["policy_ids"] = ["unknown"]
    elif kind == "duplicate-policy":
        data["policies"].append(policy)
    elif kind == "duplicate-link":
        data["links"].append(link)
    elif kind in {"duplicate-fragment", "duplicate-position"}:
        fragment = dict(policy["fragments"][0])
        if kind == "duplicate-position":
            fragment["fragment_id"] = "another-id"
        policy["fragments"].append(fragment)
    elif kind == "complete":
        data["coverage"] = "complete"
    elif kind == "review-date":
        data["checked_on"] = "2026-10-01"
    elif kind == "blank-summary":
        policy["fragments"][0]["summary"] = " "
    elif kind == "blank-reviewer":
        data["checked_by"] = " "
    else:
        extra = json.loads(json.dumps(policy))
        extra["policy_id"] = "unused"
        extra["source"]["url"] = extra["source"]["url"].replace("academic-probation-and-dismissal", "another-policy")
        data["policies"].append(extra)
    with pytest.raises(ValidationError):
        ProgramPolicyBundle.model_validate(data)


@pytest.mark.parametrize("kind", ["html", "missing-sidecar", "sidecar-date", "sidecar-url", "sidecar-size",
    "paragraph-position", "paragraph-hash", "paragraph-heading"])
def test_policy_archive_or_locator_tampering_is_rejected(tmp_path, kind):
    data, _, _, policy_dir, _ = fixture_bundle(tmp_path)
    policy = data["policies"][0]
    sidecar = policy_dir / f"{policy['source']['sha256']}.json"
    if kind == "html":
        sidecar.with_suffix(".html").write_bytes(b"tampered")
    elif kind == "missing-sidecar":
        sidecar.unlink()
    elif kind.startswith("sidecar-"):
        changed = json.loads(sidecar.read_text())
        key, value = {"sidecar-date": ("captured_at", "2026-10-02T11:00:00Z"),
            "sidecar-url": ("url", request_data()["url"].replace("academic-probation-and-dismissal", "other")),
            "sidecar-size": ("byte_count", 1)}[kind]
        changed[key] = value
        sidecar.write_text(json.dumps(changed))
    else:
        key, value = {"paragraph-position": ("paragraph_index", 1), "paragraph-hash": ("paragraph_sha256", "0" * 64),
            "paragraph-heading": ("heading", "Wrong heading")}[kind]
        policy["fragments"][0][key] = value
    with pytest.raises((ValueError, OSError)):
        verify_policy_source(PolicyEvidence.model_validate(policy), policy_dir)


@pytest.mark.parametrize("key,value", [("plan_id", "unknown"), ("campus", "seattle"),
    ("pathway", "align"), ("concentration", "other"), ("plan_content_sha256", "0" * 64)])
def test_exact_link_scope_and_revision_are_required(tmp_path, key, value):
    data, bundle_file, plan_file, policy_dir, program_dir = fixture_bundle(tmp_path)
    data["links"][0][key] = value
    bundle_file.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="Linked plan"):
        audit_bundle(bundle_file, [plan_file], policy_dir, program_dir)


def test_plan_change_draft_duplicate_and_program_byte_corruption_fail_closed(tmp_path):
    _, bundle_file, plan_file, policy_dir, program_dir = fixture_bundle(tmp_path)
    original = json.loads(plan_file.read_text())
    for kind in ("revision", "draft", "duplicate"):
        changed = json.loads(json.dumps(original))
        if kind == "revision":
            changed[0]["notes"] += " changed"
        elif kind == "draft":
            changed[0]["review_status"] = "draft"
            links = json.loads(bundle_file.read_text())
            links["links"][0]["plan_content_sha256"] = content_hash(ProgramPlan.model_validate(changed[0]))
            bundle_file.write_text(json.dumps(links))
        else:
            changed.append(changed[0])
        plan_file.write_text(json.dumps(changed))
        with pytest.raises(ValueError):
            audit_bundle(bundle_file, [plan_file], policy_dir, program_dir)
    links = json.loads(bundle_file.read_text())
    links["links"][0]["plan_content_sha256"] = content_hash(ProgramPlan.model_validate(original[0]))
    bundle_file.write_text(json.dumps(links))
    plan_file.write_text(json.dumps(original))
    next(program_dir.glob("*.html")).write_bytes(b"tampered")
    with pytest.raises(ValueError):
        audit_bundle(bundle_file, [plan_file], policy_dir, program_dir)


@pytest.mark.parametrize("concentration,college,label", [
    ("computer-science", "khoury", "Computer Science—Khoury College of Computer Sciences"),
    ("data-design-visualization", "camd", "Data Design and Visualization—College of Arts, Media and Design"),
    ("engineering-theory-modeling", "engineering", "Engineering Theory and Modeling—College of Engineering"),
])
def test_ds_home_college_comes_from_exact_concentration_list_not_ds_prefix(concentration, college, label):
    data = json.loads((ROOT / "data/program_plan_seed/boston_2026_2027_extended_rules.json").read_text())[1]
    data["concentration"] = concentration
    plan = ProgramPlan.model_validate(data)
    source = f'<div id="textcontainer"><ul><li>{label}</li></ul></div>'.encode()
    assert verify_home_college(plan, source) == college
    for invalid in (b'<div id="textcontainer"><p>DS courses belong to Khoury</p></div>',
            source.replace(label.encode(), b'Computer Science-other-college'), source + source):
        with pytest.raises(ValueError):
            verify_home_college(plan, invalid)


def test_unknown_pathway_cannot_inherit_a_home_college_from_prefix():
    data = json.loads((ROOT / "data/program_plan_seed/boston_2026_2027_extended_rules.json").read_text())[1]
    data["pathway"] = "align"
    with pytest.raises(ValueError, match="supported"):
        verify_home_college(ProgramPlan.model_validate(data), html())


def test_program_breadcrumb_not_free_body_text_is_college_evidence(tmp_path):
    _, _, plan_file, _, program_dir = fixture_bundle(tmp_path)
    plan = ProgramPlan.model_validate(json.loads(plan_file.read_text())[0])
    content = next(program_dir.glob("*.html")).read_bytes()
    assert verify_home_college(plan, content) == "khoury"
    for invalid in (content.replace(b'id="breadcrumb"', b'id="not-breadcrumb"'),
            content.replace(b'/graduate/computer-information-science/', b'/graduate/engineering/'), content + content):
        with pytest.raises(ValueError):
            verify_home_college(plan, invalid)


@pytest.mark.parametrize("kind", ["url", "title", "edition"])
def test_conflicting_request_declarations_fail_before_network(tmp_path, kind):
    requests = [request_data(), request_data()]
    if kind == "url":
        requests[1]["authority"] = "engineering"
    elif kind == "title":
        requests[1]["page_title"] = "Different title"
    else:
        requests[1]["catalog_year"] = "2025-2026"
    file = tmp_path / "requests.json"
    file.write_text(json.dumps(requests))
    def no_network(request):
        pytest.fail("Invalid declarations must fail before any network call")
    with httpx.Client(transport=httpx.MockTransport(no_network)) as client, pytest.raises(ValueError):
        capture_policy_sources(file, tmp_path / "archive", client=client)


def test_conflicting_sidecar_preserves_inputs_even_when_html_half_is_missing(tmp_path):
    file = tmp_path / "requests.json"
    file.write_text(json.dumps([request_data()]))
    archive = tmp_path / "archive"
    with httpx.Client(transport=httpx.MockTransport(lambda request:
            httpx.Response(200, content=html(), headers={"content-type": "text/html"}))) as client:
        metadata = capture_policy_sources(file, archive, client=client)[0]
        path = archive / f"{metadata['sha256']}.json"
        metadata["page_title"] = "Conflict"
        path.write_text(json.dumps(metadata))
        path.with_suffix(".html").unlink()
        before = {p.name: p.read_bytes() for p in archive.iterdir()}
        with pytest.raises(ValueError, match="conflict"):
            capture_policy_sources(file, archive, client=client)
        assert {p.name: p.read_bytes() for p in archive.iterdir()} == before


@pytest.mark.parametrize("tamper", [False, True])
def test_real_cli_is_readonly_and_invalid_input_has_no_partial_json(tmp_path, tamper):
    _, bundle_file, plan_file, policy_dir, program_dir = fixture_bundle(tmp_path)
    if tamper:
        next(policy_dir.glob("*.html")).write_bytes(b"tampered")
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    result = subprocess.run([sys.executable, str(ROOT / "scripts/audit_program_policy_sources.py"),
        "--bundle-file", str(bundle_file), "--plan-file", str(plan_file), "--policy-source-dir", str(policy_dir),
        "--program-source-dir", str(program_dir)], capture_output=True, text=True, timeout=30)
    assert result.returncode == int(tamper)
    if tamper:
        assert result.stdout == "" and "no verified report" in result.stderr
    else:
        assert json.loads(result.stdout)["verification"] == "archive_identity_paragraph_positions_and_exact_plan_links"
    assert {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


def test_curated_public_bundle_has_only_finite_partial_exact_links_and_no_verdict():
    bundle = ProgramPolicyBundle.model_validate_json((SEEDS / "boston_2026_2027_evidence.json").read_text())
    requests = [PolicySourceRequest.model_validate(d) for d in json.loads((SEEDS / "boston_2026_2027_source_requests.json").read_text())]
    assert len(bundle.policies) == len(requests) == 18
    assert len(bundle.links) == 7 and sum(len(p.fragments) for p in bundle.policies) == 77
    assert {p.source.url for p in bundle.policies} == {r.url for r in requests}
    plans = {}
    for filename in ("boston_2026_2027_extended_rules.json", "boston_2026_2027_pathway_rules.json"):
        for data in json.loads((ROOT / "data/program_plan_seed" / filename).read_text()):
            plan = ProgramPlan.model_validate(data)
            plans[plan.plan_id] = plan
    for link in bundle.links:
        plan = plans[link.plan_id]
        assert link.scope_key() == plan.scope_key() and link.plan_content_sha256 == content_hash(plan)
        assert link.campus == "boston" and link.catalog_year == "2026-2027"
    assert not any(link.program_id == "ds-ms" and link.pathway == "align" for link in bundle.links)
    # Policy documents are deliberately separate: old plan/storage hashes remain
    # unchanged and no optional field silently mutates the persisted contract.
    assert "policy_evidence" not in ProgramPlan.model_fields


@pytest.mark.parametrize("kind", ["page-title", "edition", "ambiguous-edition", "footer-body"])
def test_consistently_rehashed_wrong_policy_identity_still_fails(tmp_path, kind):
    data, _, _, policy_dir, _ = fixture_bundle(tmp_path)
    policy = data["policies"][0]
    content = html()
    if kind == "page-title":
        content = html(title="Wrong policy")
    elif kind == "edition":
        content = html(year="2025-2026")
    elif kind == "ambiguous-edition":
        content += b"<p>2025-2026 Edition</p>"
    else:
        content = content.replace(b'id="textcontainer"', b'id="footer"')
    source = policy["source"]
    source["sha256"] = hashlib.sha256(content).hexdigest()
    source["byte_count"] = len(content)
    (policy_dir / f"{source['sha256']}.html").write_bytes(content)
    (policy_dir / f"{source['sha256']}.json").write_text(json.dumps(source))
    with pytest.raises(ValueError):
        verify_policy_source(PolicyEvidence.model_validate(policy), policy_dir)


def test_university_only_link_still_needs_correct_home_college_evidence(tmp_path):
    data, bundle_file, plan_file, policy_dir, program_dir = fixture_bundle(tmp_path)
    # A general university rule has no college enum conflict at schema level;
    # the program-page association must still be checked independently.
    data["policies"][0]["authority"] = "university"
    data["policies"][0]["source"]["url"] = "https://catalog.northeastern.edu/graduate/academic-policies-procedures/minimum-gpa/"
    next(policy_dir.glob("*.json")).write_text(json.dumps(data["policies"][0]["source"]))
    data["links"][0]["home_college"] = "engineering"
    bundle_file.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="home college"):
        audit_bundle(bundle_file, [plan_file], policy_dir, program_dir)


def test_association_review_cannot_predate_newer_plan_review(tmp_path):
    data, bundle_file, plan_file, policy_dir, program_dir = fixture_bundle(tmp_path)
    plans = json.loads(plan_file.read_text())
    plans[0]["checked_on"] = "2026-10-03"
    data["links"][0]["plan_content_sha256"] = content_hash(ProgramPlan.model_validate(plans[0]))
    bundle_file.write_text(json.dumps(data))
    plan_file.write_text(json.dumps(plans))
    with pytest.raises(ValueError, match="predates"):
        audit_bundle(bundle_file, [plan_file], policy_dir, program_dir)


def test_audit_never_opens_database_or_network(tmp_path, monkeypatch):
    import sqlite3
    _, bundle_file, plan_file, policy_dir, program_dir = fixture_bundle(tmp_path)
    def forbidden(*args, **kwargs):
        pytest.fail("Offline policy audit must not open a DB or HTTP client")
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(httpx, "Client", forbidden)
    assert audit_bundle(bundle_file, [plan_file], policy_dir, program_dir)["coverage"] == "selected_fragments_only"


@pytest.mark.parametrize("body", ["<p></p>", "<p>" + "x" * 20_001 + "</p>", "<p>p</p>" * 301])
def test_empty_or_unbounded_policy_paragraphs_are_not_truncated_to_success(body):
    with pytest.raises(ValueError):
        policy_paragraphs(html(body=body))
