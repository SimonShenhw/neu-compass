"""Exact share links pin a public plan revision, never personal applicability."""

import copy
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from app.deep_links import apply_deep_link, share_url
from db.program_plan_repository import content_hash
from schemas.program_plan import ProgramPlan

ROOT = Path(__file__).resolve().parent.parent
PAGES = ['Search', 'Programs', 'Co-op']
FIELDS = ['plan_v', 'program', 'plan', 'campus', 'catalog_year', 'pathway', 'concentration', 'plan_revision']


def plans():
    return [ProgramPlan.model_validate(p)
        for name in ['boston_2026_2027_extended_rules.json', 'boston_2026_2027_pathway_rules.json']
        for p in json.loads((ROOT / 'data/program_plan_seed' / name).read_text())]


def plan():
    return plans()[5]


def params(item=None):
    item = item or plan()
    return dict(plan_v='1', program=item.program_id, plan=item.plan_id, campus=item.campus,
        catalog_year=item.catalog_year, pathway=item.pathway, concentration=json.dumps(item.concentration, ensure_ascii=False),
        plan_revision=content_hash(item))


def body(item=None):
    item = item or plan()
    return dict(program_id=item.program_id, prefix='CS', full_name='Synthetic program', notes=None,
        semesters=[], plan_schema_available=True,
        plans=[p.model_dump(mode='json') for p in plans() if p.program_id == item.program_id])


class Query(dict):
    def get_all(self, key):
        value = self.get(key)
        return value if isinstance(value, list) else ([] if value is None else [value])


class Surface:
    def __init__(self, query=None):
        self.query_params = Query(query or {})
        self.session_state = {}
        self.warnings = []

    def warning(self, text):
        self.warnings.append(text)


def fake_api(monkeypatch, response):
    import app.api_client as api
    calls = []
    class Client:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def get_program_curriculum(self, program_id):
            calls.append(program_id)
            if isinstance(response, Exception):
                raise response
            return copy.deepcopy(response)
        def list_programs(self):
            return [{'program_id': 'cs-ms', 'prefix': 'CS', 'full_name': 'Synthetic program'}]
        def resolve_course(self, ref):
            pytest.fail('A plan link must not use course resolve/search/model traffic')
    monkeypatch.setattr(api, 'ApiClient', Client)
    return calls


@pytest.mark.parametrize('index', range(7))
def test_all_current_scopes_produce_exact_replayable_revision_links(index):
    from app.program_plan_links import read_plan_link, resolve_plan_link
    item = plans()[index]
    url = share_url('https://x.dev//', plan=item)
    query = Query(parse_qs(urlsplit(url).query, keep_blank_values=True))
    target = read_plan_link(query)
    assert target.scope_key() == item.scope_key() and target.plan_content_sha256 == content_hash(item)
    assert set(query) == set(FIELDS)
    status, result = resolve_plan_link(target, body(item))
    assert status == 'ready' and result == item


@pytest.mark.parametrize('field', FIELDS)
def test_partial_plan_link_is_not_downgraded_to_a_family_link(field):
    from app.program_plan_links import read_plan_link
    query = params(); query.pop(field)
    with pytest.raises(ValueError):
        read_plan_link(Query(query))


@pytest.mark.parametrize('field', FIELDS)
def test_repeated_plan_parameters_are_rejected_even_if_identical(field):
    from app.program_plan_links import read_plan_link
    query = params(); query[field] = [query[field], query[field]]
    with pytest.raises(ValueError):
        read_plan_link(Query(query))


@pytest.mark.parametrize('field,value', [
    ('plan_v', '2'), ('program', 'CS'), ('program', ' cs-ms '), ('plan', '../bad'),
    ('campus', 'Boston'), ('catalog_year', '2026-2028'), ('pathway', 'general'),
    ('concentration', ' '), ('plan_revision', 'f' * 63), ('plan_revision', 'F' * 64),
    ('plan', 'x' * 101), ('concentration', json.dumps('x' * 101)), ('program', 12),
])
def test_bad_query_values_are_not_normalized_or_guessed(field, value):
    from app.program_plan_links import read_plan_link
    query = params(); query[field] = value
    with pytest.raises(ValueError):
        read_plan_link(Query(query))


def test_plan_and_course_are_not_a_two_destination_link():
    from app.program_plan_links import read_plan_link
    query = params(); query['course'] = 'CS-5800'
    with pytest.raises(ValueError):
        read_plan_link(Query(query))
    with pytest.raises(ValueError):
        share_url('https://x.dev', course='CS-5800', plan=plan())


def test_producer_rejects_conflicting_family_and_unreviewed_plan():
    with pytest.raises(ValueError):
        share_url('https://x.dev', program='ds-ms', plan=plan())
    item = plan().model_copy(update={'review_status': 'draft'})
    with pytest.raises(ValueError):
        share_url('https://x.dev', plan=item)


@pytest.mark.parametrize('change,status', [
    ('missing', 'missing'), ('revision', 'stale'), ('scope', 'stale'),
    ('duplicate-id', 'unusable'), ('duplicate-scope', 'unusable'), ('bad-model', 'unusable'),
    ('wrong-family', 'unusable'), ('wrong-body', 'unusable'), ('no-schema', 'unavailable'),
])
def test_current_api_identity_scope_and_revision_are_all_required(change, status):
    from app.program_plan_links import read_plan_link, resolve_plan_link
    current = body(); item = next(d for d in current['plans'] if d['plan_id'] == plan().plan_id)
    if change == 'missing': current['plans'].remove(item)
    elif change == 'revision': item['notes'] += ' Revised'
    elif change == 'scope': item['campus'] = 'seattle'
    elif change == 'duplicate-id': current['plans'].append(copy.deepcopy(item))
    elif change == 'duplicate-scope':
        current['plans'].append(dict(item, plan_id='same-scope-another-id'))
    elif change == 'bad-model': item['source_url'] = 'https://evil.test/'
    elif change == 'wrong-family': current['program_id'] = 'ds-ms'
    elif change == 'wrong-body': current = []
    elif change == 'no-schema': current['plan_schema_available'] = False
    result, selected = resolve_plan_link(read_plan_link(Query(params())), current)
    assert result == status and selected is None


def test_success_bypasses_stale_curriculum_cache_and_is_one_shot(monkeypatch):
    calls = fake_api(monkeypatch, body())
    st = Surface(params())
    st.session_state['_curriculum_cache'] = {'cs-ms': {'plans': []}}
    original = copy.deepcopy(st.query_params)
    apply_deep_link(st, pages=PAGES)
    assert calls == ['cs-ms'] and st.session_state['selected_program_id'] == 'cs-ms'
    assert st.session_state['nav_page'] == PAGES[1]
    assert st.session_state['_curriculum_cache']['cs-ms'] == body()
    assert st.session_state['_program_plan_link_pending']['plan_id'] == plan().plan_id
    st.session_state['nav_page'] = PAGES[2]
    apply_deep_link(st, pages=PAGES)
    assert calls == ['cs-ms'] and st.session_state['nav_page'] == PAGES[2]
    assert st.query_params == original


@pytest.mark.parametrize('code', [429, 503])
def test_transient_failures_retry_without_old_selection(monkeypatch, code):
    from app.api_client import ApiError
    calls = fake_api(monkeypatch, ApiError(code, 'private detail'))
    st = Surface(params()); st.session_state['program-plan-cs-ms'] = 'previous-choice'
    apply_deep_link(st, pages=PAGES)
    assert calls == ['cs-ms'] and 'program-plan-cs-ms' not in st.session_state
    assert '_program_plan_link_applied' not in st.session_state
    assert 'private detail' not in ' '.join(st.warnings)
    fake_api(monkeypatch, body()); apply_deep_link(st, pages=PAGES)
    assert st.session_state['_program_plan_link_pending']['plan_id'] == plan().plan_id


def test_dead_target_settles_and_does_not_repeatedly_fetch(monkeypatch):
    from app.api_client import ApiError
    calls = fake_api(monkeypatch, ApiError(404, 'not found'))
    st = Surface(params()); apply_deep_link(st, pages=PAGES); apply_deep_link(st, pages=PAGES)
    assert calls == ['cs-ms'] and st.warnings
    assert '_program_plan_link_pending' not in st.session_state


def test_invalid_plan_conflict_does_not_fetch_or_echo_untrusted_text(monkeypatch):
    calls = fake_api(monkeypatch, body())
    query = params(); query['course'] = '`[bad](https://evil.test)`'
    st = Surface(query); st.session_state['selected_program_id'] = 'cs-ms'
    st.session_state['program-plan-cs-ms'] = 'old'
    apply_deep_link(st, pages=PAGES)
    assert calls == [] and st.warnings and st.session_state.get('selected_program_id') is None
    assert 'program-plan-cs-ms' not in st.session_state
    assert not any('evil.test' in warning for warning in st.warnings)


def test_changed_link_in_same_session_is_a_new_explicit_navigation(monkeypatch):
    fake_api(monkeypatch, body())
    st = Surface(params()); apply_deep_link(st, pages=PAGES)
    item = plans()[0]; st.query_params = Query(params(item))
    apply_deep_link(st, pages=PAGES)
    assert st.session_state['_program_plan_link_pending']['plan_id'] == item.plan_id


def test_unknown_query_keys_and_auth_secrets_are_not_part_of_target():
    from app.program_plan_links import read_plan_link
    query = params(); query.update(state='private-oauth-state', token='private-token')
    target = read_plan_link(Query(query))
    assert 'private' not in target.model_dump_json()


@pytest.mark.parametrize('value', ['中文方向', 'none', 'null', '[label](https://evil.test)'])
def test_concentration_is_an_exact_literal_not_a_null_alias(value):
    from app.program_plan_links import read_plan_link, resolve_plan_link
    item = plan().model_copy(update={'concentration': value})
    query = Query(parse_qs(urlsplit(share_url('https://x.dev', plan=item)).query, keep_blank_values=True))
    target = read_plan_link(query)
    assert target.concentration == value
    assert resolve_plan_link(target, dict(body(), plans=[item.model_dump(mode='json')]))[0] == 'ready'
    assert resolve_plan_link(target, body())[0] == 'stale'


def test_query_budget_and_large_document_set_are_rejected():
    from app.program_plan_links import read_plan_link, resolve_plan_link
    query = params(); query['plan'] = 'x' * 2049
    with pytest.raises(ValueError): read_plan_link(Query(query))
    current = body(); current['plans'] = [current['plans'][0]] * 101
    assert resolve_plan_link(read_plan_link(Query(params())), current) == ('unusable', None)


def test_draft_current_document_cannot_be_selected_from_a_forged_hash():
    from app.program_plan_links import read_plan_link, resolve_plan_link
    item = plan().model_copy(update={'review_status': 'draft'})
    target = read_plan_link(Query(params(item)))
    assert resolve_plan_link(target, dict(body(), plans=[item.model_dump(mode='json')])) == ('draft', None)


@pytest.mark.parametrize('change', ['revision', 'scope', 'duplicates', 'family', 'bad-pending'])
def test_pending_target_is_revalidated_before_any_widget_selection(change):
    from app.program_plan_links import PlanLink, consume_plan_selection
    from tests.test_program_plan_view import FakeSurface
    st = FakeSurface(); st.session_state['selected'] = 'old'
    st.session_state['_program_plan_link_pending'] = PlanLink.from_plan(plan()).model_dump(mode='json')
    docs = body()['plans']; current = next(d for d in docs if d['plan_id'] == plan().plan_id)
    if change == 'revision': current['notes'] += ' Changed'
    elif change == 'scope': current['campus'] = 'seattle'
    elif change == 'duplicates': docs.append(copy.deepcopy(current))
    elif change == 'family': current['program_id'] = 'ds-ms'
    elif change == 'bad-pending': st.session_state['_program_plan_link_pending'] = {'url': 'https://evil.test'}
    consume_plan_selection(st, docs, key='selected', program_id='cs-ms')
    assert 'selected' not in st.session_state and '_program_plan_link_pending' not in st.session_state
    assert st.captions and st.texts == st.markdowns == []


def test_family_browser_does_not_render_another_family_plan():
    from app.program_plan_view import render_program_plans
    from tests.test_program_plan_view import FakeSurface
    foreign = plans()[1].model_dump(mode='json')
    st = FakeSurface(choice=foreign['plan_id'])
    assert render_program_plans(st, [foreign], key='selected', program_id='cs-ms') is None
    assert not st.texts and not st.markdowns and not st.selectors


def test_real_api_link_resolution_is_readonly_and_has_no_query_log_traffic(api_client, empty_db, monkeypatch):
    import httpx
    import app.api_client as api_module
    from db.program_plan_repository import ProgramPlanRepository
    from db.program_repository import ProgramRepository
    from schemas.program import Program
    item = plan()
    ProgramRepository(empty_db).upsert_program(Program(program_id=item.program_id, prefix='CS', full_name='CS'))
    ProgramPlanRepository(empty_db).store(item)
    before = empty_db.total_changes
    original = api_module.ApiClient
    requests = []
    def handle(request):
        requests.append((request.method, request.url.path))
        response = api_client.get(request.url.path)
        return httpx.Response(response.status_code, json=response.json())
    monkeypatch.setattr(api_module, 'ApiClient', lambda **kwargs: original(
        base_url='http://test', transport=httpx.MockTransport(handle), **kwargs))
    st = Surface(params(item)); apply_deep_link(st, pages=PAGES)
    assert requests == [('GET', '/programs/cs-ms')]
    assert empty_db.total_changes == before
    assert st.session_state['_program_plan_link_pending']['plan_id'] == item.plan_id


def widget(monkeypatch, response=None, query=None):
    from streamlit.testing.v1 import AppTest
    import app.program_policy_view as policy
    calls = fake_api(monkeypatch, response or body())
    monkeypatch.setattr(policy, 'load_selected_program_policy_evidence', lambda st, item: st.caption('Policy stub'))
    app = AppTest.from_string('''
import streamlit as st
from app.deep_links import apply_deep_link
from app.program_view import _render_curriculum
pages = ['Search', 'Programs', 'Co-op']
apply_deep_link(st, pages=pages)
nav = st.radio('Page', pages, key='nav_page')
if nav == 'Programs' and st.session_state.get('selected_program_id'):
    _render_curriculum(st, st.session_state['selected_program_id'])
''')
    app.query_params.update(query or params())
    return app.run(timeout=45), calls


def test_real_widgets_select_link_once_and_produce_the_same_revision(monkeypatch):
    app, calls = widget(monkeypatch)
    assert not app.exception and calls == ['cs-ms']
    assert app.selectbox[0].value == plan().plan_id
    query = parse_qs(urlsplit(app.code[0].value).query, keep_blank_values=True)
    assert query == {k: [v] for k, v in params().items()}
    assert any('不是你的适用年度' in c.value for c in app.caption)
    app.selectbox[0].set_value(None).run(timeout=45)
    assert not app.exception and app.selectbox[0].value is None and calls == ['cs-ms']
    assert '?program=cs-ms' in app.code[0].value and 'plan=' not in app.code[0].value


def test_real_refresh_clears_scope_and_does_not_reapply_address_bar_link(monkeypatch):
    app, calls = widget(monkeypatch)
    next(b for b in app.button if b.key == 'prog-refresh-cs-ms').click().run(timeout=45)
    assert not app.exception and app.selectbox[0].value is None
    assert calls == ['cs-ms', 'cs-ms']
    assert app.query_params == {k: [v] for k, v in params().items()}


def test_real_stale_link_has_warning_without_any_rule_or_share_box(monkeypatch):
    current = body()
    next(d for d in current['plans'] if d['plan_id'] == plan().plan_id)['notes'] += ' Changed'
    app, calls = widget(monkeypatch, current)
    assert not app.exception and calls == ['cs-ms']
    assert app.warning and not app.text and not app.code and not app.selectbox
    assert any('内容版本已变化' in w.value for w in app.warning)


def test_invalid_json_response_fails_closed_without_private_detail_or_retry(monkeypatch):
    calls = fake_api(monkeypatch, ValueError('private-json-body'))
    st = Surface(params()); apply_deep_link(st, pages=PAGES); apply_deep_link(st, pages=PAGES)
    assert calls == ['cs-ms'] and st.warnings
    assert st.session_state.get('selected_program_id') is None
    assert 'private-json-body' not in ' '.join(st.warnings)


def test_success_can_replace_a_malformed_session_cache(monkeypatch):
    fake_api(monkeypatch, body())
    st = Surface(params()); st.session_state['_curriculum_cache'] = ['invalid-cache']
    apply_deep_link(st, pages=PAGES)
    assert st.session_state['_curriculum_cache']['cs-ms'] == body()


def test_main_entry_processes_auth_before_links_and_links_before_bound_nav():
    import ast
    tree = ast.parse((ROOT / 'app/streamlit_app.py').read_text(encoding='utf-8-sig'))
    render = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'render')
    lines = {}
    for call in ast.walk(render):
        if not isinstance(call, ast.Call): continue
        if isinstance(call.func, ast.Name) and call.func.id in {'handle_oauth_callback', 'apply_deep_link'}:
            lines[call.func.id] = call.lineno
        if isinstance(call.func, ast.Attribute) and call.func.attr == 'radio':
            if any(k.arg == 'key' and isinstance(k.value, ast.Constant) and k.value.value == 'nav_page' for k in call.keywords):
                lines['nav'] = call.lineno
    assert lines['handle_oauth_callback'] < lines['apply_deep_link'] < lines['nav']


@pytest.mark.parametrize('value', ['', 'None', 'false', '123', '[]', '{}', '[' * 1000 + ']' * 1000])
def test_concentration_query_accepts_only_nonempty_nullable_string_scalars(value):
    from app.program_plan_links import read_plan_link
    query = params(); query['concentration'] = value
    with pytest.raises(ValueError): read_plan_link(Query(query))


def test_real_new_link_in_same_session_can_select_another_revision_scope(monkeypatch):
    app, _ = widget(monkeypatch)
    item = plans()[0]
    app.query_params.update(params(item))
    app.run(timeout=45)
    assert not app.exception and app.selectbox[0].value == item.plan_id
    assert parse_qs(urlsplit(app.code[0].value).query)['plan'] == [item.plan_id]


def test_real_legacy_family_link_does_not_choose_a_scope(monkeypatch):
    app, calls = widget(monkeypatch, query={'program': 'CS'})
    assert not app.exception and app.selectbox[0].value is None
    assert calls == ['cs-ms'] and 'plan=' not in app.code[0].value


def test_real_manual_draft_selection_can_only_share_the_family(monkeypatch):
    current = body(); current['plans'][0]['review_status'] = 'draft'
    app, _ = widget(monkeypatch, response=current, query={'program': 'cs-ms'})
    app.selectbox[0].set_value(current['plans'][0]['plan_id']).run(timeout=45)
    assert not app.exception and 'plan=' not in app.code[0].value
    assert any('这里只分享项目入口' in c.value for c in app.caption)


def test_stale_link_evicts_only_its_family_cache_before_manual_browsing(monkeypatch):
    current = body()
    next(d for d in current['plans'] if d['plan_id'] == plan().plan_id)['notes'] += ' Changed'
    fake_api(monkeypatch, current)
    st = Surface(params()); st.session_state['_curriculum_cache'] = {'cs-ms': body(), 'ds-ms': {'sentinel': True}}
    apply_deep_link(st, pages=PAGES)
    assert st.session_state['_curriculum_cache'] == {'ds-ms': {'sentinel': True}}
    assert st.session_state.get('selected_program_id') is None


def test_producer_cannot_use_an_unvalidated_dictionary():
    with pytest.raises(ValueError): share_url('https://x.dev', plan=plan().model_dump())
