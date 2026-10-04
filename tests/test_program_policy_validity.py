"""Validity/exception evidence is not a deadline, admission or credit calculator."""

import json

import pytest

from app.program_policy_view import render_program_policy_evidence
from schemas.program_policy import ProgramPolicyBundle, paragraph_hash, policy_lists, policy_paragraphs
from tests.test_program_plan_view import FakeSurface
from tests.test_program_policy_evidence import ROOT, html


def bundle():
    return ProgramPolicyBundle.model_validate_json(
        (ROOT / 'data/program_policy_seed/boston_2026_2027_evidence.json').read_text())


@pytest.mark.parametrize('wrapper', ['<nav>{}</nav>', '<footer>{}</footer>',
    '<div role="navigation">{}</div>', '<div class="notinpdf onthispage" name="otp1">{}</div>'])
def test_internal_navigation_cannot_become_paragraph_list_or_nearest_heading(wrapper):
    toc = wrapper.format('<h2>Navigation only</h2><p>Not policy</p><ul><li>Not a condition</li></ul>')
    content = html(body='<h2>Actual policy</h2>' + toc + '<p>Actual paragraph</p><ul><li>Actual condition</li></ul>')
    assert policy_paragraphs(content) == [('Actual policy', 'Actual paragraph')]
    assert policy_lists(content) == [('Actual policy', 'Actual condition')]


def test_navigation_nested_inside_a_real_list_does_not_pollute_its_text():
    content = html(body='<p>Context</p><ul><li>Approval needed.'
        '<div class="onthispage"><ul><li>Page index only</li></ul></div></li><li>Exception reviewed.</li></ul>')
    assert policy_lists(content) == [(None, 'Approval needed. Exception reviewed.')]


def test_ordinary_links_and_notinpdf_alone_remain_real_policy_text():
    content = html(body='<h2>Policy</h2><div class="notinpdf"><p>Actual paragraph.</p>'
        '<ul><li>See <a href="#approval">approval</a> conditions.</li></ul></div>')
    assert policy_paragraphs(content) == [('Policy', 'Actual paragraph.')]
    assert policy_lists(content) == [('Policy', 'See approval conditions.')]


def test_validity_increment_is_explicit_and_does_not_recapture_existing_pages():
    data = bundle()
    requests = json.loads((ROOT / 'data/program_policy_seed/boston_2026_2027_validity_source_requests.json').read_text())
    expected = {'university-credit-validity', 'university-masters-regulations', 'university-program-regulations',
        'engineering-program-completion', 'engineering-certificate-sharing'}
    selected = {p.policy_id: p for p in data.policies if p.policy_id in expected}
    assert set(selected) == expected and len(requests) == 5
    assert {p['url'] for p in requests} == {p.source.url for p in selected.values()}
    assert 'camd-masters' not in selected
    assert all(p.source.catalog_year == '2026-2027' for p in selected.values())


@pytest.mark.parametrize('home', ['khoury', 'camd', 'engineering'])
def test_validity_links_do_not_borrow_engineering_certificates_or_change_plan_revisions(home):
    from db.program_plan_repository import content_hash
    from schemas.program_plan import ProgramPlan
    plans = {}
    for name in ('boston_2026_2027_extended_rules.json', 'boston_2026_2027_pathway_rules.json'):
        for item in json.loads((ROOT / 'data/program_plan_seed' / name).read_text()):
            plan = ProgramPlan.model_validate(item)
            plans[plan.plan_id] = plan
    for link in (item for item in bundle().links if item.home_college == home):
        assert {'university-credit-validity', 'university-masters-regulations', 'university-program-regulations'} <= set(link.policy_ids)
        assert ('engineering-certificate-sharing' in link.policy_ids) == (home == 'engineering')
        assert ('engineering-program-completion' in link.policy_ids) == (home == 'engineering')
        plan = plans[link.plan_id]
        assert link.plan_content_sha256 == content_hash(plan) and link.scope_key() == plan.scope_key()


@pytest.mark.parametrize('policy_id,fragment_id,terms', [
    ('university-credit-validity', 'seven-years-extension-not-deadline', ['七年', '除非', '延期']),
    ('camd-masters', 'college-credit-validity', ['七年']),
    ('camd-masters', 'extension-petition-certification-recommendation', ['petition', '剩余', '未变', '建议']),
    ('camd-masters', 'leave-not-automatic-time-extension', ['medical', '不', 'incomplete']),
    ('university-program-regulations', 'major-concentration-same-catalog-year', ['同一', '年度', '不能']),
    ('university-program-regulations', 'later-concentration-full-transition', ['整体', 'major', 'concentration']),
    ('university-program-regulations', 'nonrepeatable-limits-unresolved-wording', ['两门', '一次', '最近']),
    ('university-masters-regulations', 'neu-earned-unapplied-credit', ['Northeastern', '尚未', '其他机构', '有效期']),
    ('university-masters-regulations', 'minimum-thirty-not-program-total', ['30', '本科层级']),
    ('university-masters-regulations', 'exam-is-conditional', ['可能', '考试']),
    ('university-masters-regulations', 'thesis-if-required-approval', ['若', '批准']),
    ('engineering-program-completion', 'degree-applied-gpa-core-separate', ['计入该学位', '3.000', 'C', '额外']),
    ('engineering-certificate-sharing', 'current-student-admission-conditions', ['good standing', 'fall', 'spring', 'final', 'summer']),
    ('engineering-certificate-sharing', 'completion-before-or-with-degree', ['之前', '同一学期']),
    ('engineering-certificate-sharing', 'eligible-course-and-petition', ['项目要求', 'petition']),
    ('engineering-certificate-sharing', 'disciplinary-eight-with-listed-exceptions', ['多数', '8', '16', '批准']),
    ('engineering-certificate-sharing', 'seis-sixteen-not-universal', ['SEIS', '16']),
    ('engineering-certificate-sharing', 'no-certificate-double-counting', ['不能', '证书']),
    ('engineering-certificate-sharing', 'no-triple-counting-plusone', ['不能', 'PlusOne']),
    ('engineering-certificate-sharing', 'undergraduate-applied-versus-excess', ['本科', '不能', '额外']),
])
def test_reviewed_validity_and_exception_qualifiers_are_not_dropped(policy_id, fragment_id, terms):
    policy = next(p for p in bundle().policies if p.policy_id == policy_id)
    fragment = next(f for f in policy.fragments if f.fragment_id == fragment_id)
    assert all(term in fragment.summary for term in terms)
    assert fragment.limitation.strip() and policy.coverage == 'selected_fragments_only'


def test_conflicting_repeat_wording_is_explicit_not_an_automatic_priority_rule():
    policies = {p.policy_id: p for p in bundle().policies}
    fragment = next(f for f in policies['university-program-regulations'].fragments
        if f.fragment_id == 'nonrepeatable-limits-unresolved-wording')
    assert all(term in fragment.limitation for term in ['Minimum', 'Khoury', '不一致', '确认', '不自动'])
    assert '较大者' in policies['university-minimum-gpa'].fragments[2].summary
    assert '两次' in policies['khoury-retaking'].fragments[0].summary
    for policy_id, index in [('university-minimum-gpa', 2), ('khoury-retaking', 0)]:
        assert all(term in policies[policy_id].fragments[index].limitation
            for term in ['All Graduate Degree Programs', '不一致', '确认', '不', '优先级'])


def test_certificate_exception_list_is_whole_and_not_claimed_as_personal_eligibility():
    policy = next(p for p in bundle().policies if p.policy_id == 'engineering-certificate-sharing')
    fragment = next(f for f in policy.fragments if f.fragment_id == 'disciplinary-exception-list')
    assert fragment.source_kind == 'list' and fragment.paragraph_index == 5
    assert fragment.heading == 'Course Double Counting'
    assert all(word in fragment.summary for word in ['General Mechanical', '指定证书'])
    assert '不' in fragment.limitation and 'DS' in fragment.limitation


def test_renderer_keeps_deadline_unknown_and_extension_approval_distinct(tmp_path):
    from tests.test_program_policy_view import setup_reader
    plan, _, reader = setup_reader(tmp_path)
    data = reader.read(plan).model_dump(mode='json')
    fragment = data['policies'][0]['fragments'][0]
    fragment.update(summary='Credit valid for a limited period unless extension is approved.',
        limitation='Personal dates, deadline and approval unknown. No automatic eligibility.',
        source_paragraph='Synthetic time limit and conditional extension.',
        paragraph_sha256=paragraph_hash('Synthetic time limit and conditional extension.'))
    st = FakeSurface()
    render_program_policy_evidence(st, plan, data)
    assert f"限制／未知：{fragment['limitation']}" in st.texts
    assert not any('eligibility' in item for item in st.markdowns)
