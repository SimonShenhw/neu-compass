"""Credit policy evidence keeps conditions, source kinds and colleges separate."""

import copy
import hashlib
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

import schemas.program_policy as policy_schema
from app.program_policy_view import render_program_policy_evidence
from db.program_plan_repository import ProgramPlanRepository
from db.program_repository import ProgramRepository
from rag.program_policy_evidence import ProgramPolicyReader
from schemas.program import Program
from schemas.program_plan import ProgramPlan
from schemas.program_policy import PolicyEvidence, PolicyFragment, ProgramPolicyBundle, paragraph_hash, policy_paragraphs
from schemas.program_policy_view import ProgramPolicyView
from scripts.audit_program_policy_sources import audit_bundle
from scripts.capture_program_policy_sources import capture_policy_sources
from tests.test_program_plan_view import FakeSurface
from tests.test_program_policy_evidence import ROOT, fixture_bundle, html, request_data

LIST_TEXT = "Only after approval. Limit applies. Exception needs a petition. No automatic credit."
BODY = ('<h2>Standing</h2><p>Independent synthetic policy paragraph.</p>'
    '<ul><li>Only after approval.</li><li>Limit applies.<ol><li>Exception needs a petition.</li></ol></li>'
    '<li>No automatic credit.</li></ul><h3>Separate</h3><ol><li>Different credential.</li></ol>')


def list_fixture(tmp_path):
    data, file, plans, policy_dir, program_dir = fixture_bundle(tmp_path)
    content = html(body=BODY)
    source = data["policies"][0]["source"]
    source.update(sha256=hashlib.sha256(content).hexdigest(), byte_count=len(content))
    (policy_dir / f"{source['sha256']}.html").write_bytes(content)
    (policy_dir / f"{source['sha256']}.json").write_text(json.dumps(source))
    data["policies"][0]["fragments"].append(dict(fragment_id="approval-list", source_kind="list",
        paragraph_index=0, heading="Standing", paragraph_sha256=paragraph_hash(LIST_TEXT),
        summary="Synthetic conditional limit.", limitation="No approval or qualification inferred."))
    file.write_text(json.dumps(data))
    plan = ProgramPlan.model_validate(json.loads(plans.read_text())[0])
    return data, file, plans, policy_dir, program_dir, plan


def test_whole_outer_lists_preserve_nested_conditions_without_shifting_legacy_paragraphs():
    content = html(body=BODY) + b'<ul><li>Outside body</li></ul>'
    assert policy_paragraphs(content) == [("Standing", "Independent synthetic policy paragraph.")]
    assert policy_schema.policy_lists(content) == [("Standing", LIST_TEXT), ("Separate", "Different credential.")]


def test_no_lists_is_valid_and_nested_list_count_does_not_become_outer_positions():
    assert policy_schema.policy_lists(html()) == []
    body = '<p>context</p><ul><li>Outer<ol>' + '<li>condition</li>' * 301 + '</ol></li></ul>'
    blocks = policy_schema.policy_lists(html(body=body))
    assert len(blocks) == 1 and blocks[0][1].count('condition') == 301


def test_paragraphs_inside_lists_keep_old_paragraph_indexing():
    content = html(body='<h2>Approval</h2><p>Before</p><ul><li><p>Nested paragraph</p></li></ul><p>After</p>')
    assert policy_paragraphs(content) == [('Approval', 'Before'), ('Approval', 'Nested paragraph'), ('Approval', 'After')]
    assert policy_schema.policy_lists(content) == [('Approval', 'Nested paragraph')]


def test_source_kind_defaults_to_paragraph_and_positions_are_typed(tmp_path):
    data, *_ = list_fixture(tmp_path)
    model = PolicyEvidence.model_validate(data["policies"][0])
    assert model.fragments[0].source_kind == "paragraph" and model.fragments[1].source_kind == "list"
    assert model.fragments[0].paragraph_index == model.fragments[1].paragraph_index == 0


@pytest.mark.parametrize("body", ['<ul></ul>', '<ul><li> </li></ul>', '<ul><li>' + 'x' * 20_001 + '</li></ul>', '<ul><li>x</li></ul>' * 301],
    ids=['empty', 'blank', 'long', 'too-many'])
def test_list_budget_rejects_empty_or_oversized_inputs_without_truncation(body):
    with pytest.raises(ValueError):
        policy_schema.policy_lists(html(body='<p>context</p>' + body))


@pytest.mark.parametrize("kind", ["missing", "duplicate"])
def test_list_body_must_be_unique(kind):
    content = html(body=BODY)
    if kind == "missing":
        content = content.replace(b'id="textcontainer"', b'id="other"')
    else:
        content += b'<div id="textcontainer"><ul><li>extra</li></ul></div>'
    with pytest.raises(ValueError):
        policy_schema.policy_lists(content)


@pytest.mark.parametrize("kind", ["table", "li", "guess", "", None])
def test_unknown_source_kind_is_rejected(tmp_path, kind):
    data, *_ = list_fixture(tmp_path)
    item = data["policies"][0]["fragments"][1]
    item["source_kind"] = kind
    with pytest.raises(ValidationError):
        PolicyFragment.model_validate(item)


def test_duplicate_list_position_is_rejected_but_same_numeric_paragraph_is_allowed(tmp_path):
    data, *_ = list_fixture(tmp_path)
    policy = data["policies"][0]
    PolicyEvidence.model_validate(policy)
    duplicate = copy.deepcopy(policy["fragments"][1])
    duplicate["fragment_id"] = "other-id"
    policy["fragments"].append(duplicate)
    with pytest.raises(ValidationError, match="Duplicate"):
        PolicyEvidence.model_validate(policy)


@pytest.mark.parametrize("kind", ["source-kind", "position", "heading", "hash", "nested-condition"])
def test_tampered_list_source_never_returns_partial_evidence(tmp_path, kind):
    data, file, plans, policy_dir, program_dir, plan = list_fixture(tmp_path)
    fragment = data["policies"][0]["fragments"][1]
    if kind == "nested-condition":
        source = data["policies"][0]["source"]
        path = policy_dir / f"{source['sha256']}.html"
        path.write_bytes(path.read_bytes().replace(b"Exception needs a petition.", b"Automatic exception."))
    else:
        key, value = {"source-kind": ("source_kind", "paragraph"), "position": ("paragraph_index", 2),
            "heading": ("heading", "Separate"), "hash": ("paragraph_sha256", "0" * 64)}[kind]
        fragment[key] = value
        file.write_text(json.dumps(data))
    view = ProgramPolicyReader(file, policy_dir, program_dir).read(plan)
    assert view.status == "unusable" and view.policies == []
    with pytest.raises(ValueError):
        audit_bundle(file, [plans], policy_dir, program_dir)


def test_capture_refuses_to_ignore_an_oversized_condition_list(tmp_path):
    requests = tmp_path / "requests.json"
    requests.write_text(json.dumps([request_data()]))
    body = '<p>context</p><ul><li>' + 'x' * 20_001 + '</li></ul>'
    with httpx.Client(transport=httpx.MockTransport(lambda request:
            httpx.Response(200, content=html(body=body), headers={"content-type": "text/html"}))) as client:
        with pytest.raises(ValueError):
            capture_policy_sources(requests, tmp_path / "archive", client=client)
    assert not (tmp_path / "archive").exists()


def test_rehashed_archive_still_cannot_drop_a_selected_nested_condition(tmp_path):
    data, file, plans, policy_dir, program_dir, plan = list_fixture(tmp_path)
    source = data['policies'][0]['source']
    content = (policy_dir / f"{source['sha256']}.html").read_bytes().replace(
        b'Exception needs a petition.', b'Exception is automatic.')
    source.update(sha256=hashlib.sha256(content).hexdigest(), byte_count=len(content))
    (policy_dir / f"{source['sha256']}.html").write_bytes(content)
    (policy_dir / f"{source['sha256']}.json").write_text(json.dumps(source))
    file.write_text(json.dumps(data))
    assert ProgramPolicyReader(file, policy_dir, program_dir).read(plan).status == 'unusable'
    with pytest.raises(ValueError, match='heading/content'):
        audit_bundle(file, [plans], policy_dir, program_dir)


def test_reader_and_offline_audit_preserve_whole_list_are_readonly_and_no_network(tmp_path, monkeypatch):
    import sqlite3
    data, file, plans, policy_dir, program_dir, plan = list_fixture(tmp_path)
    before = {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    def forbidden(*args, **kwargs):
        pytest.fail("Evidence must not open DB or network")
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(httpx, "Client", forbidden)
    view = ProgramPolicyReader(file, policy_dir, program_dir).read(plan)
    assert view.status == "ready" and len(view.policies[0].fragments) == 2
    assert view.policies[0].fragments[1].source_paragraph == LIST_TEXT
    report = audit_bundle(file, [plans], policy_dir, program_dir)
    assert report['policies'][0]['fragments'][1]['source_paragraph'] == LIST_TEXT
    assert report['policies'][0]['fragments'][1]['source_kind'] == "list"
    assert {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()} == before


def test_ui_labels_list_evidence_and_keeps_source_plaintext(tmp_path):
    _, file, _, policy_dir, program_dir, plan = list_fixture(tmp_path)
    view = ProgramPolicyReader(file, policy_dir, program_dir).read(plan).model_dump(mode='json')
    st = FakeSurface()
    render_program_policy_evidence(st, plan, view)
    assert LIST_TEXT in st.texts
    assert any('列表块 0' in text for text in st.texts)
    assert not any(LIST_TEXT in text for text in st.markdowns)


@pytest.mark.parametrize('state', ['unavailable', 'unusable', 'stale'])
def test_failure_wire_cannot_retain_usable_list_evidence(tmp_path, state):
    _, file, _, policy_dir, program_dir, plan = list_fixture(tmp_path)
    data = ProgramPolicyReader(file, policy_dir, program_dir).read(plan).model_dump(mode='json')
    data['status'] = state
    with pytest.raises(ValidationError, match='Non-ready'):
        ProgramPolicyView.model_validate(data)


def test_real_widget_displays_whole_list_and_removes_it_after_source_failure(tmp_path, monkeypatch):
    from tests.test_program_policy_view import widget_app
    data, file, _, policy_dir, program_dir, plan = list_fixture(tmp_path)
    app = widget_app(monkeypatch, plan, ProgramPolicyReader(file, policy_dir, program_dir))
    app.selectbox[0].set_value(plan.plan_id).run(timeout=45)
    assert not app.exception and any(item.value == LIST_TEXT for item in app.text)
    assert any('列表块 0' in item.value for item in app.text)
    path = policy_dir / f"{data['policies'][0]['source']['sha256']}.html"
    path.write_bytes(path.read_bytes().replace(b'No automatic credit.', b'Automatic credit.'))
    app.run(timeout=45)
    assert not app.exception and any('校验未通过' in item.value for item in app.caption)
    assert not any(LIST_TEXT in item.value for item in app.text)


def test_list_evidence_api_is_no_store_and_does_not_change_plan_or_db(api_client, empty_db, tmp_path):
    from api.dependencies import get_program_policy_reader
    _, file, _, policy_dir, program_dir, plan = list_fixture(tmp_path)
    ProgramRepository(empty_db).upsert_program(Program(program_id=plan.program_id, full_name="CS", prefix="CS"))
    repo = ProgramPlanRepository(empty_db)
    repo.store(plan)
    reader = ProgramPolicyReader(file, policy_dir, program_dir)
    api_client.app.dependency_overrides[get_program_policy_reader] = lambda: reader
    before = empty_db.total_changes
    response = api_client.get(f'/programs/{plan.program_id}/plans/{plan.plan_id}/policies')
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    view = ProgramPolicyView.model_validate(response.json())
    assert view.status == 'ready' and view.policies[0].fragments[1].source_paragraph == LIST_TEXT
    assert view.policies[0].fragments[1].source_kind == 'list'
    assert empty_db.total_changes == before and repo.list_for_program(plan.program_id) == [plan]


def test_curated_credit_bundle_keeps_all_conditions_and_exact_college_links():
    seed_dir = ROOT / 'data/program_policy_seed'
    bundle = ProgramPolicyBundle.model_validate_json((seed_dir / 'boston_2026_2027_evidence.json').read_text())
    policies = {p.policy_id: p for p in bundle.policies}
    expected = {'university-retaking': 2, 'university-substitutions': 2, 'university-transfer': 4,
        'university-credit-sharing': 4, 'khoury-retaking': 2, 'khoury-transfer': 7,
        'khoury-credit-sharing': 7, 'engineering-retake-substitution': 8}
    for key, count in expected.items():
        assert len(policies[key].fragments) == count
    assert sum(f.source_kind == 'list' for key in expected for f in policies[key].fragments) == 4
    for link in bundle.links:
        assert set(expected).intersection(link.policy_ids) == {
            key for key in expected if policies[key].authority in {'university', link.home_college}}
    substitute = policies['university-substitutions']
    assert substitute.fragments[1].heading == 'For Programs in Massachusetts, California, Maine, and Washington'
    assert '批准' in substitute.fragments[0].summary and 'Boston' in substitute.fragments[1].summary
    assert '不同' in policies['university-credit-sharing'].fragments[0].limitation
    assert '免修' in policies['khoury-credit-sharing'].fragments[-2].summary
    assert all(p.coverage == 'selected_fragments_only' for p in policies.values())
    increment = json.loads((seed_dir / 'boston_2026_2027_credit_source_requests.json').read_text())
    assert len(increment) == 8 and {p['url'] for p in increment} == {policies[key].source.url for key in expected}


@pytest.mark.parametrize('policy_id,fragment_id,required', [
    ('university-retaking', 'nonrepeatable-latest-grade-and-record', ['最近一次', '旧成绩', 'advisor', '学费']),
    ('university-transfer', 'masters-constraints-and-advanced-standing', ['30%', '3.000', '25%', 'PlusOne', '证书']),
    ('university-transfer', 'five-academic-years-at-matriculation', ['matriculation', 'academic years']),
    ('university-credit-sharing', 'credential-specific-list-with-exceptions', ['两个 credential', '50%', '除非', 'concentration', '治理']),
    ('khoury-retaking', 'nonrepeatable-two-retakes-advisor', ['两次', '批准', '最近一次']),
    ('khoury-transfer', 'before-enrollment-complete-criteria', ['3.000', '认证', '其他学位', '转入时', '五年']),
    ('khoury-transfer', 'during-enrollment-prior-approval', ['先获', 'online', 'asynchronous']),
    ('khoury-credit-sharing', 'forty-percent-and-seven-year-exception', ['40%', '32', '12', '七年', '除非']),
    ('khoury-credit-sharing', 'additional-waiver-without-transferred-credit', ['免修', '不转入学分', '个案']),
    ('engineering-retake-substitution', 'probation-extra-eight-hours', ['最低学位要求外', '合计', '8']),
    ('engineering-retake-substitution', 'substitution-only-if-retake-impossible-not-core', ['无法重修', '相似', '非 required core']),
    ('engineering-retake-substitution', 'no-substitution-in-good-standing', ['本页', 'good academic standing']),
])
def test_curated_summaries_keep_reviewed_qualifiers(policy_id, fragment_id, required):
    file = ROOT / 'data/program_policy_seed/boston_2026_2027_evidence.json'
    bundle = ProgramPolicyBundle.model_validate_json(file.read_text())
    policy = next(item for item in bundle.policies if item.policy_id == policy_id)
    fragment = next(item for item in policy.fragments if item.fragment_id == fragment_id)
    assert all(term in fragment.summary for term in required)
