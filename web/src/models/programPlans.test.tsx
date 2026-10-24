import { cleanup, render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { parsePlan, availablePlans } from './programPlans';
import { parsePolicyView } from './programPolicy';
import { programFixture } from '../fixtures/programsDemo';
import { curriculumProps, edit } from '../features/programs/programTestUtils';
import { ProgramCurriculum } from '../features/programs/ProgramCurriculum';
import type { ProgramPlanDoc, ProgramPolicyView } from '../api/programs';
const plan = () =>
  structuredClone(
    (programFixture('curriculum-cs-ms').body as { plans: ProgramPlanDoc[] })
      .plans[2]!,
  );
const policy = () =>
  structuredClone(
    programFixture('policies-cs-ms-standard-ready').body as ProgramPolicyView,
  );
const invalidPlanCases: [string, unknown][] = [
  ['plan_id', 'Bad'],
  ['plan_id', 'a'.repeat(101)],
  ['plan_id', 'x\n'],
  ['program_id', ' '],
  ['program_id', 'a'.repeat(65)],
  ['program_id', 1],
  ['campus', 'Boston'],
  ['campus', 'a'.repeat(41)],
  ['catalog_year', '2026-2028'],
  ['catalog_year', '2026-27'],
  ['pathway', 'unknown'],
  ['concentration', ' '],
  ['concentration', 'a'.repeat(101)],
  ['coverage', 'full'],
  ['review_status', 'checked'],
  ['coverage', ['partial']],
  ['review_status', ['source_checked']],
  ['checked_by', null],
  ['checked_by', ' '],
  ['checked_by', 'a'.repeat(101)],
  ['checked_on', null],
  ['checked_on', '2026-02-29'],
  ['checked_on', '2026-09-30'],
  ['source_url', 'https://catalog.northeastern.edu.evil.test/graduate/path/'],
  ['source_url', 'https://catalog.northeastern.edu/graduate/path/?x=1'],
  ['source_url', 'http://catalog.northeastern.edu/graduate/path/'],
  [
    'source_url',
    'https://catalog.northeastern.edu/archive/2025-2026/graduate/path/',
  ],
  ['source_title', ' '],
  ['source_title', 'a'.repeat(301)],
  ['source_catalog_year', '2025-2026'],
  ['source_excerpt', ' '],
  ['source_excerpt', 'a'.repeat(6001)],
  ['source_html_sha256', 'A'.repeat(64)],
  ['source_html_sha256', 'a'.repeat(63)],
  ['captured_on', '2026-04-31'],
  ['captured_on', '0000-01-01'],
  ['notes', ' '],
  ['notes', 'a'.repeat(2501)],
  ['requirements', {}],
  ['requirements.children.0.kind', 'invalid'],
];
describe('each invalid plan field is excluded without hiding the other valid versions', () => {
  it.each(invalidPlanCases.map(([path, value], i) => ({ path, value, i })))(
    '$i $path',
    ({ path, value }) => {
      const p = plan();
      edit(p, path, value);
      expect(parsePlan(p, 'cs-ms')).toEqual({ kind: 'invalid' });
      const props = curriculumProps();
      if (props.curriculum.status !== 'ready') throw new Error('fixture');
      edit(props.curriculum.data, 'plans.2', p);
      render(<ProgramCurriculum {...props} />);
      expect(
        screen.getByText('一份版本化规则格式/来源校验未通过，未显示。'),
      ).toBeInTheDocument();
      expect(screen.getByRole('combobox')).toBeInTheDocument();
      expect(document.querySelector('pre')).toBeNull();
    },
  );
});
it('complete plans reject unreviewed content and any nested unmodeled branch', () => {
  const p = plan();
  p.coverage = 'complete';
  expect(parsePlan(p, 'cs-ms').kind).toBe('invalid');
  p.requirements = {
    ...p.requirements,
    kind: 'course',
    course_code: 'CS 1',
    children: [],
  };
  expect(parsePlan(p, 'cs-ms').kind).toBe('ok');
  p.review_status = 'draft';
  expect(parsePlan(p, 'cs-ms').kind).toBe('invalid');
});
it('optional fields normalize, extra keys are ignored, dates are real and lengths count code points', () => {
  const p = plan();
  p.review_status = 'draft';
  for (const key of [
    'checked_by',
    'checked_on',
    'source_html_sha256',
    'concentration',
  ])
    edit(p, key, undefined);
  edit(p, 'future_field', true);
  p.notes = '😀'.repeat(2500);
  p.source_title = '😀'.repeat(300);
  p.captured_on = '2024-02-29';
  const parsed = parsePlan(p, 'cs-ms');
  expect(parsed.kind).toBe('ok');
  if (parsed.kind !== 'ok') return;
  expect(parsed.plan.checked_on).toBeNull();
  expect(parsed.plan.checked_by).toBeNull();
  expect(parsed.plan.concentration).toBeNull();
  p.captured_on = '1900-02-29';
  expect(parsePlan(p, 'cs-ms').kind).toBe('invalid');
  p.captured_on = '2000-02-29';
  expect(parsePlan(p, 'cs-ms').kind).toBe('ok');
  p.program_id = 'foreign';
  expect(parsePlan(p, 'cs-ms').kind).toBe('other_program');
  p.notes = '';
  expect(parsePlan(p, 'cs-ms').kind).toBe('invalid');
});
it('duplicate IDs and scopes remove every ambiguous member, with one notice and stable survivor order', () => {
  const p = plan(),
    q = plan();
  p.campus = 'seattle'; // Duplicate ID alone: scopes must not mask this guard.
  q.plan_id = 'other';
  const values = (
    programFixture('curriculum-cs-ms').body as { plans: ProgramPlanDoc[] }
  ).plans;
  for (const duplicate of [p, q]) {
    const result = availablePlans([...values, duplicate], 'cs-ms');
    expect(result.plans.map((p) => p.pathway)).toEqual([
      'align',
      'bridge',
      'standard',
    ]);
    expect(result.plans.some((p) => p.plan_id === q.plan_id)).toBe(false);
    expect(result.plans.some((x) => x.plan_id === p.plan_id)).toBe(false);
    expect(result.notes).toEqual([
      '重复的方案身份／范围存在歧义，相关版本未显示。',
    ]);
  }
});
const invalidPolicyCases: [string, unknown][] = [
  ['plan_id', 'BAD'],
  ['scope', null],
  ['scope.program_id', ' '],
  ['scope.program_id', 'a'.repeat(65)],
  ['scope.campus', 'Boston'],
  ['scope.catalog_year', '2026-2028'],
  ['scope.pathway', 'unknown'],
  ['scope.concentration', ' '],
  ['scope.concentration', 'a'.repeat(101)],
  ['plan_content_sha256', 'a'.repeat(63)],
  ['status', 'okay'],
  ['link', null],
  ['checked_by', null],
  ['checked_by', ' '],
  ['checked_by', 'a'.repeat(101)],
  ['checked_on', null],
  ['checked_on', '2026-02-30'],
  ['checked_on', '2026-10-01'],
  ['policies', []],
  ['status', ['ready']],
  ['link.home_college', ['khoury']],
  ['link.plan_id', 'other'],
  ['link.campus', 'seattle'],
  ['link.plan_content_sha256', 'b'.repeat(64)],
  ['link.home_college', 'university'],
  ['link.policy_ids', []],
  ['link.policy_ids', ['one', 'one']],
  [
    'link.policy_ids',
    ['khoury-academic-probation', 'university-academic-standing'],
  ],
  ['policies.0.policy_id', 'BAD'],
  ['policies.0.authority', 'camd'],
  ['policies.0.source.url', 'https://example.com/graduate/path/'],
  [
    'policies.0.source.url',
    'https://catalog.northeastern.edu/graduate/academic-policies-procedures/',
  ],
  [
    'policies.0.source.url',
    'https://catalog.northeastern.edu/graduate/engineering/academic-policies-procedures/a/',
  ],
  [
    'policies.0.source.url',
    'https://catalog.northeastern.edu/archive/2025-2026/graduate/academic-policies-procedures/a/',
  ],
  ['policies.0.source.catalog_year', '2025-2026'],
  ['policies.0.source.captured_at', '2026-10-02T10:00:00+00:00'],
  ['policies.0.source.captured_at', '2026-10-02T10:00:00.1234567Z'],
  ['policies.0.source.page_title', ' '],
  ['policies.0.source.page_title', 'a'.repeat(301)],
  ['policies.0.source.sha256', 'A'.repeat(64)],
  ['policies.0.fragments', []],
  ['policies.0.fragments.0.fragment_id', null],
  ['policies.0.fragments.0.source_kind', 'html'],
  ['policies.0.fragments.0.paragraph_index', -1],
  ['policies.0.fragments.0.paragraph_index', 300],
  ['policies.0.fragments.0.paragraph_index', 0.5],
  ['policies.0.fragments.0.heading', 1],
  ['policies.0.fragments.0.paragraph_sha256', 'x'],
  ['policies.0.fragments.0.summary', ' '],
  ['policies.0.fragments.0.summary', 'a'.repeat(1501)],
  ['policies.0.fragments.0.limitation', ' '],
  ['policies.0.fragments.0.limitation', 'a'.repeat(1501)],
  ['policies.0.fragments.0.source_paragraph', ''],
];
describe('policy source and identity guards each stop evidence', () => {
  it.each(invalidPolicyCases.map(([path, value], i) => ({ path, value, i })))(
    '$i $path',
    ({ path, value }) => {
      const view = policy();
      edit(view, path, value);
      expect(parsePolicyView(view)).toEqual({ kind: 'invalid' });
      const props = curriculumProps();
      props.policies = { status: 'ready', data: view };
      render(<ProgramCurriculum {...props} />);
      expect(
        screen.getByText('政策响应格式／来源字段校验未通过，未显示证据。'),
      ).toBeInTheDocument();
      expect(screen.queryAllByText('官方政策来源')).toHaveLength(0);
      expect(document.querySelector('pre')).not.toBeNull();
    },
  );
});
it('policy IDs, URLs and fragment IDs/locations must be unique, and policy order is exact', () => {
  for (const change of [
    (p: ProgramPolicyView) => {
      p.link!.policy_ids.reverse();
    },
    (p: ProgramPolicyView) => {
      p.policies[1]!.source.url = p.policies[0]!.source.url;
    },
    (p: ProgramPolicyView) => {
      p.policies[0]!.fragments.push(
        structuredClone(p.policies[0]!.fragments[0]!),
      );
    },
    (p: ProgramPolicyView) => {
      const copy = structuredClone(p.policies[0]!.fragments[0]!);
      copy.fragment_id = 'new';
      p.policies[0]!.fragments.push(copy);
    },
    (p: ProgramPolicyView) => {
      p.policies[0]!.fragments = Array(31).fill(p.policies[0]!.fragments[0]);
    },
  ]) {
    const view = policy();
    change(view);
    expect(parsePolicyView(view).kind).toBe('invalid');
  }
});
it.each(['not_linked', 'draft', 'stale', 'unavailable', 'unusable'])(
  'non-ready %s may not contain evidence, linkage or review metadata',
  (status) => {
    const p = policy();
    edit(p, 'status', status);
    expect(parsePolicyView(p).kind).toBe('invalid');
    p.policies = [];
    p.link = null;
    p.checked_by = null;
    p.checked_on = null;
    expect(parsePolicyView(p).kind).toBe('ok');
    for (const [key, value] of [
      ['checked_by', 'reviewer'],
      ['checked_on', '2026-10-03'],
      ['link', {}],
      ['policies', [{}]],
    ] as const) {
      const copy = structuredClone(p);
      edit(copy, key, value);
      expect(parsePolicyView(copy).kind).toBe('invalid');
    }
  },
);
it('missing source kind defaults to paragraph, extra keys are safe, list and paragraph positions are distinct', () => {
  const p = policy();
  edit(p, 'policies.0.fragments.0.source_kind', undefined);
  edit(p, 'future_field', 'okay');
  expect(parsePolicyView(p).kind).toBe('ok');
  const parsed = parsePolicyView(p);
  if (parsed.kind === 'ok')
    expect(parsed.view.policies[0]!.fragments[0]!.source_kind).toBe(
      'paragraph',
    );
  p.policies[0]!.fragments[0]!.summary = '😀'.repeat(1500);
  expect(parsePolicyView(p).kind).toBe('ok');
});
it('policy matching checks all scope fields before status and refuses updated review dates or draft plans', () => {
  for (const path of [
    'program_id',
    'campus',
    'catalog_year',
    'pathway',
    'concentration',
  ]) {
    const props = curriculumProps();
    const p = policy();
    const values: Record<string, string> = {
      program_id: 'other',
      campus: 'seattle',
      catalog_year: '2025-2026',
      pathway: 'align',
      concentration: 'other',
    };
    p.status = 'not_linked';
    p.policies = [];
    p.link = null;
    p.checked_by = null;
    p.checked_on = null;
    edit(p, 'scope.' + path, values[path]);
    props.policies = { status: 'ready', data: p };
    render(<ProgramCurriculum {...props} />);
    expect(
      screen.getByText(/政策响应与当前所选方案的范围／内容版本不一致/),
    ).toBeInTheDocument();
    cleanup();
  }
  for (const [path, value] of [
    ['checked_on', '2026-10-05'],
    ['review_status', 'draft'],
  ] as const) {
    const props = curriculumProps();
    if (props.curriculum.status !== 'ready') throw new Error('fixture');
    edit(props.curriculum.data, 'plans.2.' + path, value);
    render(<ProgramCurriculum {...props} />);
    expect(
      screen.getByText('方案来源对照或审核版本已变化，未显示旧政策证据。'),
    ).toBeInTheDocument();
    cleanup();
  }
});

it('malformed roots and sparse arrays fail closed, while a checked plan on the same review day is allowed', () => {
  for (const v of [null, [], 1, 'x', {}]) {
    expect(parsePlan(v, 'cs-ms').kind).toBe('invalid');
    expect(parsePolicyView(v).kind).toBe('invalid');
  }
  const p = policy();
  p.policies = Array(1);
  expect(parsePolicyView(p).kind).toBe('invalid');
  const q = policy();
  q.policies[0]!.fragments = Array(1);
  expect(parsePolicyView(q).kind).toBe('invalid');
  const r = plan();
  r.checked_on = r.captured_on;
  expect(parsePlan(r, 'cs-ms').kind).toBe('ok');
});
