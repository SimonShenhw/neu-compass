"""Exact public plan links; URL scope/revision is not a personal POS or signature."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from db.program_plan_repository import content_hash
from schemas.program_plan import ProgramPlan

QUERY_FIELDS = {
    'plan_v': 'format_version', 'program': 'program_id', 'plan': 'plan_id',
    'campus': 'campus', 'catalog_year': 'catalog_year', 'pathway': 'pathway',
    'concentration': 'concentration', 'plan_revision': 'plan_content_sha256',
}
PENDING_KEY = '_program_plan_link_pending'
APPLIED_KEY = '_program_plan_link_applied'
MESSAGES = {
    'invalid': '🔗 方案分享参数缺失、重复或冲突；未选择任何方案，请从项目列表手动选择。',
    'missing': '🔗 分享的确切方案已不可用；未改选同范围或同家族的其他版本。',
    'stale': '🔗 分享方案的范围或内容版本已变化；未自动打开新版，请重新明确选择。',
    'unusable': '🔗 当前方案身份、范围或格式存在歧义／校验失败；未选择方案。',
    'unavailable': '🔗 当前无法取得版本化方案；未用旧 seed 或其他年度替代。',
    'draft': '🔗 当前方案尚未完成来源对照；未按链接自动选定。',
}


class PlanLink(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    format_version: Literal['1'] = '1'
    program_id: str = Field(pattern=r'^[a-z0-9][a-z0-9-]{0,63}$')
    plan_id: str = Field(pattern=r'^[a-z0-9][a-z0-9-]{0,99}$')
    campus: str = Field(pattern=r'^[a-z][a-z0-9-]{0,39}$')
    catalog_year: str = Field(pattern=r'^\d{4}-\d{4}$')
    pathway: Literal['standard', 'align', 'bridge']
    concentration: str | None = Field(default=None, min_length=1, max_length=100)
    plan_content_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')

    @field_validator('catalog_year')
    @classmethod
    def edition(cls, value):
        return ProgramPlan.consecutive_years(value)

    @field_validator('concentration')
    @classmethod
    def nonblank(cls, value):
        if value is not None and not value.strip():
            raise ValueError('Blank concentration is not a declared scope')
        return value

    def scope_key(self):
        return (self.program_id, self.campus, self.catalog_year, self.pathway, self.concentration or '')

    @classmethod
    def from_plan(cls, plan: ProgramPlan):
        if not isinstance(plan, ProgramPlan):
            raise ValueError('A validated program plan is required')
        plan = ProgramPlan.model_validate(plan.model_dump())
        if plan.review_status != 'source_checked':
            raise ValueError('Share only a source-checked plan revision')
        return cls(program_id=plan.program_id, plan_id=plan.plan_id, campus=plan.campus,
            catalog_year=plan.catalog_year, pathway=plan.pathway, concentration=plan.concentration,
            plan_content_sha256=content_hash(plan))

    def query_pairs(self):
        # Non-empty nullable JSON survives query readers that drop blank values;
        # the literal concentration "null" is different from a null scope.
        return [(name, json.dumps(self.concentration, ensure_ascii=False) if name == 'concentration'
            else getattr(self, field)) for name, field in QUERY_FIELDS.items()]


def _values(query, key):
    get_all = getattr(query, 'get_all', None)
    if callable(get_all):
        return get_all(key)
    if key not in query:
        return []
    value = query[key]
    return value if isinstance(value, list) else [value]


def has_plan_link(query) -> bool:
    return any(key in query for key in QUERY_FIELDS if key != 'program')


def plan_query_token(query) -> str:
    # Only bounded public link fields, never OAuth state/token or arbitrary URL keys.
    values = [(key, len(items), [v[:2048] if isinstance(v, str) else type(v).__name__
        for v in items[:2]]) for key in QUERY_FIELDS for items in [_values(query, key)]]
    values.append(('course_present', 'course' in query))
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()


def read_plan_link(query) -> PlanLink:
    if 'course' in query:
        raise ValueError('Plan and course are different destinations')
    data, size = {}, 0
    for key, field in QUERY_FIELDS.items():
        values = _values(query, key)
        if len(values) != 1 or not isinstance(values[0], str):
            raise ValueError('Require each exact plan field once')
        value = values[0]
        size += len(value)
        if size > 2048:
            raise ValueError('Plan link outside size budget')
        if key == 'concentration':
            # Only a JSON string/null scalar; never decode nested attacker input.
            if value == 'null':
                data[field] = None
            elif value.startswith('"') and value.endswith('"'):
                data[field] = json.loads(value)
            else:
                raise ValueError('Concentration must be a nullable JSON string')
        else:
            data[field] = value
    return PlanLink.model_validate(data)


def resolve_plan_documents(target: PlanLink, documents) -> tuple[str, ProgramPlan | None]:
    if not isinstance(documents, list) or len(documents) > 100:
        return 'unusable', None
    try:
        target = PlanLink.model_validate(target.model_dump())
        plans = [ProgramPlan.model_validate(d.model_dump() if isinstance(d, ProgramPlan) else d)
            for d in documents]
    except ValueError:
        return 'unusable', None
    ids = Counter(p.plan_id for p in plans)
    scopes = Counter(p.scope_key() for p in plans)
    if any(p.program_id != target.program_id or ids[p.plan_id] != 1 or scopes[p.scope_key()] != 1 for p in plans):
        return 'unusable', None
    plan = next((p for p in plans if p.plan_id == target.plan_id), None)
    if plan is None:
        return 'missing', None
    if plan.scope_key() != target.scope_key() or content_hash(plan) != target.plan_content_sha256:
        return 'stale', None
    if plan.review_status != 'source_checked':
        return 'draft', None
    return 'ready', plan


def resolve_plan_link(target: PlanLink, body) -> tuple[str, ProgramPlan | None]:
    if not isinstance(body, dict) or body.get('program_id') != target.program_id:
        return 'unusable', None
    if body.get('plan_schema_available') is not True:
        return 'unavailable', None
    return resolve_plan_documents(target, body.get('plans'))


def clear_plan_link_selection(state) -> None:
    previous = state.get('selected_program_id')
    if isinstance(previous, str):
        state.pop(f'program-plan-{previous}', None)
    state.pop(PENDING_KEY, None)
    state['selected_program_id'] = None


def consume_plan_selection(st, documents, *, key: str, program_id: str) -> None:
    """Consume before the plan widget instantiates; revalidate its actual inputs."""
    data = st.session_state.pop(PENDING_KEY, None)
    if data is None:
        return
    st.session_state.pop(key, None)
    try:
        target = PlanLink.model_validate(data)
        if target.program_id != program_id:
            raise ValueError('Pending link is for another family')
    except ValueError:
        st.caption(MESSAGES['invalid'])
        return
    status, selected = resolve_plan_documents(target, documents)
    if selected is None:
        st.caption(MESSAGES[status])
        return
    st.session_state[key] = selected.plan_id
    st.caption('🔗 已定位分享的确切方案与版本；这不是你的适用年度或个人资格确认。')
