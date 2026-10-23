import { render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import type { ProgramNode, RequisiteNode } from '../api/requisites';
import {
  CourseRequisites,
  INVALID,
} from '../features/requisites/CourseRequisites';
import {
  edit,
  listing,
  twoYears,
} from '../features/requisites/requisitesTestUtils';
import { parseRequisites } from './requisites';

const doc = 'documents.0';
const section = `${doc}.requisites.prerequisite`;
const root = `${section}.rule`;
const leafPath = `${root}.children.0.children.0`;
const context = 'program_contexts.0';
const plan = `${context}.plans.0`;
const program = `${plan}.requirements`;
const select = `${program}.children.1`;
const invalid: [string, unknown][] = [
  ['schema_available', 1],
  ['has_any_stored_records', null],
  ['documents', {}],
  ['program_contexts', null],
  ['warnings', [1]],
  ['unusable_records', -1],
  ['unusable_records', 1.5],
  ['unusable_records', '0'],
  ['documents.0', null],
  ...['course_id', 'course_code', 'course_name', 'imported_at'].map(
    (key): [string, unknown] => [`${doc}.${key}`, 1],
  ),
  [`${doc}.catalog_year`, '2026-2028'],
  [`${doc}.catalog_year`, '26-27'],
  [`${doc}.catalog_year`, '2026-2027\n'],
  [`${doc}.source`, null],
  [`${doc}.source.catalog_year`, '2025-2026'],
  [`${doc}.source.captured_at`, 1],
  [`${doc}.source.sha256`, 'A'.repeat(64)],
  [`${doc}.source.sha256`, 'a'.repeat(63)],
  [`${doc}.source.sha256`, 'a'.repeat(64) + '\n'],
  ...[
    'https://evil.example/course-descriptions/cs/',
    'javascript:alert(1)',
    'https://catalog.northeastern.edu/course-descriptions/ds/',
    'https://catalog.northeastern.edu/course-descriptions/cs/?x=1',
    'https://catalog.northeastern.edu/course-descriptions/cs/\n',
  ].map((url): [string, unknown] => [`${doc}.source.url`, url]),
  [`${doc}.requisites`, null],
  [section, null],
  [`${section}.status`, 'partial'],
  [`${section}.raw_text`, ' \n'],
  [`${section}.reason`, 'oops'],
  [`${section}.rule`, null],
  [root + '.children', []],
  [root + '.kind', 'select'],
  [root + '.course_code', 'CS 1'],
  [root + '.minimum_grade', 'B'],
  [root + '.academic_level', 'Graduate'],
  [root + '.concurrent_allowed', true],
  [leafPath + '.children', [{}]],
  [leafPath + '.course_code', null],
  [leafPath + '.minimum_grade', 'E'],
  [leafPath + '.academic_level', 'Doctoral'],
  [leafPath + '.concurrent_allowed', 1],
  [`${doc}.description_evidence`, []],
  [`${doc}.description_evidence.status`, 'okay'],
  [`${doc}.description_evidence.paragraphs`, [null]],
  [`${doc}.description_evidence.candidates`, null],
  [`${doc}.description_evidence.candidates.0`, null],
  [`${doc}.description_evidence.candidates.0.paragraph_index`, -1],
  [`${doc}.description_evidence.candidates.0.paragraph_index`, 100],
  [`${doc}.description_evidence.candidates.0.paragraph_index`, 0.5],
  [`${doc}.description_evidence.candidates.0.markers`, []],
  [`${doc}.description_evidence.candidates.0.markers`, [1]],
  [`${doc}.credit_hours`, []],
  ...['raw_text', 'minimum', 'maximum'].map((key): [string, unknown] => [
    `${doc}.credit_hours.${key}`,
    4,
  ]),
  [`${doc}.credit_hours.kind`, 'estimate'],
  [context, null],
  [`${context}.course_code`, 'CS 9999'],
  [`${context}.catalog_year`, '2024-2025'],
  [`${context}.schema_available`, false],
  [`${context}.schema_available`, 'true'],
  [`${context}.plans`, {}],
  [`${context}.unusable_records`, -1],
  [`${context}.unreviewed_records`, 0.5],
  [`${context}.warnings`, [1]],
  [plan, null],
  ...[
    'plan_id',
    'program_id',
    'campus',
    'source_excerpt',
    'notes',
    'captured_on',
    'checked_on',
    'source_catalog_year',
  ].map((key): [string, unknown] => [`${plan}.${key}`, 1]),
  [`${plan}.catalog_year`, '2025-2026'],
  [`${plan}.pathway`, 'unknown'],
  [`${plan}.coverage`, 'unknown'],
  [`${plan}.concentration`, 0],
  [`${plan}.source_html_sha256`, 'A'.repeat(64)],
  [`${plan}.source_html_sha256`, 'c'.repeat(64) + '\n'],
  ...[
    'https://example.com/graduate/x/',
    'http://catalog.northeastern.edu/graduate/x/',
    'https://catalog.northeastern.edu/graduate/x/?y=1',
    'https://catalog.northeastern.edu/graduate/x/\n',
    'https://catalog.northeastern.edu/undergraduate/x/',
  ].map((url): [string, unknown] => [`${plan}.source_url`, url]),
  [program, null],
  [`${program}.kind`, 'unknown'],
  [`${program}.label`, 0],
  [`${program}.children`, []],
  [`${program}.children.0.course_code`, null],
  [`${select}.course_codes`, [1]],
  [`${select}.subject_codes`, null],
  [`${select}.excluded_course_codes`, [1]],
  [`${select}.course_ranges`, {}],
  [`${select}.course_ranges`, [{ start: 5000, end: 'CS 5999' }]],
  [`${select}.course_ranges`, [{ start: 'CS 5000', end: null }]],
  ...['min_courses', 'min_credits', 'min_areas'].map(
    (key): [string, unknown] => [`${select}.${key}`, 1.5],
  ),
  [`${select}.areas`, []],
  [`${select}.areas`, { AI: [1] }],
];
it.each(invalid.map(([path, value], index) => ({ path, value, index })))(
  'invalid field $index $path rejects the entire listing and retains navigation only',
  ({ path, value }) => {
    const data = listing();
    edit(data, path, value);
    expect(parseRequisites(data).kind).toBe('invalid');
    const { container } = render(
      <CourseRequisites
        course={twoYears.body}
        requisites={data}
        prerequisites={twoYears.body.prerequisites}
        onOpenCourse={vi.fn()}
      />,
    );
    expect(screen.getByText(INVALID)).toBeVisible();
    expect(
      screen.getByRole('heading', { name: '去看看这些先修课' }),
    ).toBeVisible();
    expect(
      container.querySelectorAll(
        '[data-rule-tree], [data-row-label], [data-kind="select"]',
      ),
    ).toHaveLength(0);
  },
);
it.each([undefined, null])(
  'older API absent value %s is not invalid',
  (value) => expect(parseRequisites(value)).toEqual({ kind: 'absent' }),
);
it.each([false, 0, '', [], {}])('non-listing shape %s is invalid', (value) =>
  expect(parseRequisites(value)).toEqual({ kind: 'invalid' }),
);
it('extra keys are ignored and credit strings are not reformatted or semantically reinterpreted', () => {
  const data = listing();
  edit(data, 'future_key', { arbitrary: true });
  edit(data, `${doc}.source.future`, 1);
  edit(data, `${doc}.credit_hours.minimum`, '04.00');
  edit(data, `${doc}.credit_hours.maximum`, '04.00');
  expect(parseRequisites(data).kind).toBe('ok');
});
it('duplicate context pairs and plan IDs fail closed', () => {
  const data = listing();
  data.program_contexts.push(structuredClone(data.program_contexts[0]!));
  expect(parseRequisites(data).kind).toBe('invalid');
  data.program_contexts.pop();
  data.program_contexts[0]!.plans.push(
    structuredClone(data.program_contexts[0]!.plans[0]!),
  );
  expect(parseRequisites(data).kind).toBe('invalid');
});
it.each([
  ['cs-5800-nothing-listed', 'raw_text', 'x'],
  ['cs-5800-nothing-listed', 'rule', {}],
  ['cs-5800-nothing-listed', 'reason', 'x'],
  ['ds-5220-unparsed-old-record', 'raw_text', null],
  ['ds-5220-unparsed-old-record', 'rule', {}],
  ['ds-5220-unparsed-old-record', 'reason', ''],
  ['ds-5220-unparsed-old-record', 'reason', null],
])('section invariants for %s %s', (caseName, field, value) => {
  const data = listing(caseName!);
  edit(data, `${section}.${field}`, value);
  expect(parseRequisites(data).kind).toBe('invalid');
});
it('optional branches require one child and explicit activation text', () => {
  for (const [field, value] of [
    ['activate_when', null],
    ['children', []],
    ['children', [{}, {}]],
  ] as const) {
    const data = listing();
    edit(
      data,
      `program_contexts.0.plans.1.requirements.children.1.${field}`,
      value,
    );
    expect(parseRequisites(data).kind).toBe('invalid');
  }
});
it('a non-consecutive catalog year alone rejects an otherwise consistent listing', () => {
  // Rename the year everywhere it must match, so only the "second year is the next one" rule can refuse it.
  const relabel = (value: string) => {
    const data = listing();
    const document = data.documents[0]!;
    const old = document.catalog_year;
    document.catalog_year = value;
    document.source.catalog_year = value;
    for (const c of data.program_contexts.filter(
      (c) => c.catalog_year === old,
    )) {
      c.catalog_year = value;
      for (const p of c.plans) p.catalog_year = value;
    }
    return parseRequisites(data).kind;
  };
  expect(relabel('2027-2028')).toBe('ok');
  expect(relabel('2026-2028')).toBe('invalid');
});
it('one bad document rejects the whole listing even when no program context points at it', () => {
  const data = listing();
  data.program_contexts = [];
  expect(parseRequisites(data).kind).toBe('ok');
  data.documents[1]!.source.sha256 = 'A'.repeat(64);
  expect(parseRequisites(data).kind).toBe('invalid');
});
it('an optional branch with two valid children is rejected', () => {
  const data = listing();
  const optional =
    data.program_contexts[0]!.plans[1]!.requirements.children[1]!;
  expect(optional.kind).toBe('optional');
  optional.children = [
    optional.children[0]!,
    structuredClone(optional.children[0]!),
  ];
  expect(parseRequisites(data).kind).toBe('invalid');
});
const leaf: RequisiteNode = {
  kind: 'course',
  course_code: 'CS 1',
  minimum_grade: null,
  academic_level: null,
  concurrent_allowed: false,
  children: [],
};
const group = (children: RequisiteNode[]): RequisiteNode =>
  ({
    kind: 'all_of',
    course_code: null,
    minimum_grade: null,
    academic_level: null,
    concurrent_allowed: false,
    children,
  }) as RequisiteNode;
it('course trees accept exactly 120 nodes and depth 10; reject 121 and depth 11 including deep corequisites', () => {
  const data = listing();
  edit(data, root, group(Array.from({ length: 119 }, () => leaf)));
  expect(parseRequisites(data).kind).toBe('ok');
  edit(data, root, group(Array.from({ length: 120 }, () => leaf)));
  expect(parseRequisites(data).kind).toBe('invalid');
  let tree: RequisiteNode = leaf;
  for (let i = 1; i < 10; i++) tree = group([tree, leaf]);
  edit(data, root, tree);
  expect(parseRequisites(data).kind).toBe('ok');
  edit(data, 'documents.0.requisites.corequisite.rule', group([tree, leaf]));
  expect(parseRequisites(data).kind).toBe('invalid');
});
it('program trees accept exactly 120 nodes and depth 8; reject 121 and depth 9', () => {
  const data = listing();
  const base = data.program_contexts[0]!.plans[0]!.requirements;
  const leaf: ProgramNode = {
    ...base,
    kind: 'course',
    course_code: 'CS 1',
    children: [],
  };
  const group = (children: ProgramNode[]): ProgramNode => ({
    ...base,
    kind: 'all_of',
    children,
  });
  edit(data, program, group(Array.from({ length: 119 }, () => leaf)));
  expect(parseRequisites(data).kind).toBe('ok');
  edit(data, program, group(Array.from({ length: 120 }, () => leaf)));
  expect(parseRequisites(data).kind).toBe('invalid');
  let tree = leaf;
  for (let i = 1; i < 8; i++) tree = group([tree, leaf]);
  edit(data, program, tree);
  expect(parseRequisites(data).kind).toBe('ok');
  edit(data, program, group([tree, leaf]));
  expect(parseRequisites(data).kind).toBe('invalid');
});
it('valid optional evidence nulls, archive links and shape-only integers remain accepted', () => {
  const data = listing();
  edit(data, `${doc}.description_evidence`, null);
  edit(data, `${doc}.credit_hours`, null);
  edit(data, `${plan}.source_html_sha256`, null);
  edit(
    data,
    `${plan}.source_url`,
    'https://catalog.northeastern.edu/archive/2025-2026/graduate/x/',
  );
  edit(data, `${select}.min_courses`, -1);
  expect(parseRequisites(data).kind).toBe('ok');
});
