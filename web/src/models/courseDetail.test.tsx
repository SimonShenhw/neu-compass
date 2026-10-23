import { render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { parseCourseDetail } from './courseDetail';
import {
  CourseDetail,
  INVALID_DETAIL,
} from '../features/course-detail/CourseDetail';
import {
  detailData,
  detailView,
  expandDetail,
  setDetail,
} from '../features/course-detail/detailTestUtils';

const badFields: {
  path: string;
  value: unknown;
  field: string;
  fallback: unknown;
}[] = [
  ...[1, {}, null].map((value) => ({
    path: 'term',
    value,
    field: 'term',
    fallback: null,
  })),
  ...[-1, 13, 1.5, '4', true].map((value) => ({
    path: 'credits',
    value,
    field: 'credits',
    fallback: null,
  })),
  {
    path: 'delivery_mode',
    value: 'remote',
    field: 'delivery_mode',
    fallback: null,
  },
  ...[-1, Infinity, NaN, '7.5'].map((value) => ({
    path: 'workload_hours_per_week',
    value,
    field: 'workload_hours_per_week',
    fallback: null,
  })),
  ...[0, 6, Infinity, NaN, '4'].map((value) => ({
    path: 'difficulty_score',
    value,
    field: 'difficulty_score',
    fallback: null,
  })),
  ...['professor', 'topics_covered', 'skill_tags', 'career_relevance'].map(
    (field) => ({ path: field, value: ['good', 1], field, fallback: [] }),
  ),
  {
    path: 'grading_components',
    value: {},
    field: 'grading_components',
    fallback: [],
  },
  {
    path: 'grading_components.1.name',
    value: '',
    field: 'grading_components',
    fallback: [],
  },
  ...[-0.1, 1.1, Infinity, NaN, '0.5'].map((value) => ({
    path: 'grading_components.1.weight',
    value,
    field: 'grading_components',
    fallback: [],
  })),
  {
    path: 'program_context',
    value: {},
    field: 'program_context',
    fallback: [],
  },
  ...['program_name', 'requirement_type'].map((field) => ({
    path: `program_context.1.${field}`,
    value: 1,
    field: 'program_context',
    fallback: [],
  })),
  ...[0, 9, 1.5, '2'].map((value) => ({
    path: 'program_context.1.semester_recommended',
    value,
    field: 'program_context',
    fallback: [],
  })),
  ...['permitted_tools', 'banned_tools'].map((field) => ({
    path: `ai_policy.${field}`,
    value: [null],
    field: 'ai_policy',
    fallback: null,
  })),
  {
    path: 'ai_policy.disclosure_required',
    value: 1,
    field: 'ai_policy',
    fallback: null,
  },
  { path: 'ai_policy.notes', value: {}, field: 'ai_policy', fallback: null },
  {
    path: 'evidence_snippets',
    value: {},
    field: 'evidence_snippets',
    fallback: [],
  },
  ...['field', 'source_id', 'quote'].map((field) => ({
    path: `evidence_snippets.1.${field}`,
    value: null,
    field: 'evidence_snippets',
    fallback: [],
  })),
  ...[-0.1, 1.1, Infinity, NaN, '0.5'].map((value) => ({
    path: 'evidence_snippets.1.confidence',
    value,
    field: 'evidence_snippets',
    fallback: [],
  })),
  ...['missing_fields', 'warnings', 'source_review_ids'].map((field) => ({
    path: `answer_evidence.${field}`,
    value: [1],
    field: 'answer_evidence',
    fallback: null,
  })),
];
it.each(badFields.map((item, index) => ({ ...item, index })))(
  'bad detail field $index $path hides only its own block',
  ({ path, value, field, fallback }) => {
    const baseline = detailView(),
      data = detailData();
    expect(parseCourseDetail(data)).toEqual({ kind: 'ok', body: baseline });
    setDetail(data, path, value);
    expect(parseCourseDetail(data)).toEqual({
      kind: 'ok',
      body: { ...baseline, [field]: fallback },
    });
  },
);
it.each([
  null,
  [],
  0,
  {},
  ...['course_id', 'primary_code', 'primary_name'].flatMap((field) => [
    { ...detailData(), [field]: '' },
    { ...detailData(), [field]: null },
    { ...detailData(), [field]: 1 },
  ]),
])(
  'invalid identity %j rejects the whole page including requisites',
  (data) => {
    expect(parseCourseDetail(data)).toEqual({ kind: 'invalid' });
    const { container } = render(
      <CourseDetail
        course={data}
        compare={[]}
        onAddToCompare={vi.fn()}
        onOpenCourse={vi.fn()}
      />,
    );
    expect(container.textContent).toBe(INVALID_DETAIL);
    expect(
      container.querySelector('[data-kind="requisites_panel"]'),
    ).toBeNull();
  },
);
const badSnapshots: [string, unknown][] = [
  ['course_code', 'CS 12'],
  ['course_code', 1],
  ['course_name', ''],
  ['course_name', null],
  ['description', {}],
  ['description', 'x'.repeat(20001)],
  ['credits', -1],
  ['credits', 13],
  ['credits', 1.5],
  ['credits', '4'],
  ['prereq_codes', [null]],
  ['prereq_codes', null],
  ['snapshot_id', 1],
  ['imported_at', 'not-a-time'],
  ['imported_at', '2026-02-30T03:00:00Z'],
  ['imported_at', null],
  ['retrieved_at', 0],
  ['retrieved_at', '2026-09-29T03:00:00+24:00'],
  ['catalog_url', 'https://catalog.northeastern.edu/course-descriptions/ds/'],
  ['catalog_url', 'https://example.com/course-descriptions/cs/'],
  ['catalog_url', 'http://catalog.northeastern.edu/course-descriptions/cs/'],
  [
    'catalog_url',
    'https://catalog.northeastern.edu/course-descriptions/cs/?x=1',
  ],
  ['catalog_url', 'https://catalog.northeastern.edu/course-descriptions/cs/\n'],
];
it.each(badSnapshots.map(([path, value], index) => ({ path, value, index })))(
  'bad snapshot $index $path emits both failures and no description or anchors',
  async ({ path, value }) => {
    const data = detailData();
    expect(parseCourseDetail(data)).toEqual({ kind: 'ok', body: detailView() });
    setDetail(data, `answer_evidence.catalog.${path}`, value);
    const result = parseCourseDetail(data);
    expect(
      result.kind === 'ok' && result.body.answer_evidence?.catalog.kind,
    ).toBe('invalid');
    const { container } = render(
      <CourseDetail
        course={data}
        compare={[]}
        onAddToCompare={vi.fn()}
        onOpenCourse={vi.fn()}
      />,
    );
    await expandDetail(container);
    expect(
      screen.getByText(
        '目录存档没有通过格式或来源校验，所以不显示描述和链接。',
      ),
    ).toBeVisible();
    expect(
      screen.getByText('目录快照格式或来源校验未通过；未显示链接。'),
    ).toBeVisible();
    expect(container.querySelectorAll('a')).toHaveLength(0);
    expect(
      screen.queryByText(/Covers supervised learning, model selection/),
    ).not.toBeInTheDocument();
    expect(screen.getByText('主题')).toBeVisible();
  },
);
it.each([undefined, null, {}, [], '', 0, false])(
  'Python-falsy catalog %j is absent rather than a failed snapshot',
  (value) => {
    const data = detailData();
    setDetail(data, 'answer_evidence.catalog', value);
    const result = parseCourseDetail(data);
    expect(
      result.kind === 'ok' && result.body.answer_evidence?.catalog,
    ).toEqual({ kind: 'absent' });
  },
);
it.each([true, 1, 'bad', [null]])(
  'nonempty non-snapshot %j is invalid, not absent',
  (value) => {
    const data = detailData();
    setDetail(data, 'answer_evidence.catalog', value);
    const result = parseCourseDetail(data);
    expect(
      result.kind === 'ok' && result.body.answer_evidence?.catalog,
    ).toEqual({ kind: 'invalid' });
  },
);
it('snapshot extras and malformed ID strings do not invalidate a usable catalog; optional defaults match Python', () => {
  const data = detailData();
  setDetail(data, 'answer_evidence.catalog.future', true);
  setDetail(data, 'answer_evidence.catalog.course_code', ' cs6140 ');
  setDetail(data, 'answer_evidence.catalog.snapshot_id', 'not-a-digest');
  for (const field of [
    'description',
    'credits',
    'prereq_codes',
    'retrieved_at',
  ])
    setDetail(data, `answer_evidence.catalog.${field}`, undefined);
  const result = parseCourseDetail(data);
  expect(
    result.kind === 'ok' && result.body.answer_evidence?.catalog,
  ).toMatchObject({
    kind: 'ok',
    snapshot: {
      course_code: 'CS 6140',
      description: null,
      credits: null,
      prereq_codes: [],
      retrieved_at: null,
      snapshot_id: 'not-a-digest',
    },
  });
});
it('description limits count Unicode code points, not UTF-16 units', () => {
  const data = detailData();
  setDetail(data, 'answer_evidence.catalog.description', '𐐀'.repeat(20000));
  let result = parseCourseDetail(data);
  expect(
    result.kind === 'ok' && result.body.answer_evidence?.catalog.kind,
  ).toBe('ok');
  setDetail(data, 'answer_evidence.catalog.description', '𐐀'.repeat(20001));
  result = parseCourseDetail(data);
  expect(
    result.kind === 'ok' && result.body.answer_evidence?.catalog.kind,
  ).toBe('invalid');
});
it('catalog code and official URL subject agree independently of the page identity', () => {
  const data = detailData();
  setDetail(data, 'answer_evidence.catalog.course_code', ' ds5220 ');
  setDetail(
    data,
    'answer_evidence.catalog.catalog_url',
    'https://catalog.northeastern.edu/course-descriptions/ds/',
  );
  let result = parseCourseDetail(data);
  expect(
    result.kind === 'ok' && result.body.answer_evidence?.catalog.kind,
  ).toBe('ok');
  setDetail(
    data,
    'answer_evidence.catalog.catalog_url',
    'https://catalog.northeastern.edu/course-descriptions/cs/',
  );
  result = parseCourseDetail(data);
  expect(
    result.kind === 'ok' && result.body.answer_evidence?.catalog.kind,
  ).toBe('invalid');
});
it.each([undefined, null, {}, 0, 'bad'])(
  'optional evidence %j preserves independent snippets and other fields',
  (value) => {
    const data = detailData();
    data.answer_evidence = value;
    const result = parseCourseDetail(data);
    expect(result.kind).toBe('ok');
    if (result.kind !== 'ok') return;
    expect(result.body.evidence_snippets).toHaveLength(4);
    expect(result.body.answer_evidence).toEqual(
      value && typeof value === 'object'
        ? {
            catalog: { kind: 'absent' },
            missing_fields: [],
            warnings: [],
            source_review_ids: [],
          }
        : null,
    );
  },
);
it.each([undefined, null])(
  'missing/null evidence arrays %s default independently to empty',
  (value) => {
    const data = detailData();
    for (const field of ['missing_fields', 'warnings', 'source_review_ids'])
      setDetail(data, `answer_evidence.${field}`, value);
    const result = parseCourseDetail(data);
    expect(result.kind === 'ok' && result.body.answer_evidence).toMatchObject({
      missing_fields: [],
      warnings: [],
      source_review_ids: [],
      catalog: { kind: 'ok' },
    });
  },
);
it('extras are ignored, program_id is not a display gate and requisites pass through by identity', () => {
  const data = detailData();
  const rules = { arbitrary: true };
  data.course_requisites = rules;
  data.prerequisites = ['raw'];
  data.future = { ignored: true };
  setDetail(data, 'program_context.0.program_id', undefined);
  const result = parseCourseDetail(data);
  expect(result.kind).toBe('ok');
  if (result.kind !== 'ok') return;
  expect(result.body.program_context).toHaveLength(2);
  expect(result.body.course_requisites).toBe(rules);
  expect(result.body.prerequisites).toBe(data.prerequisites);
});
it('a sparse array is not silently accepted as a typed list', () => {
  const data = detailData();
  data.professor = new Array(1);
  const result = parseCourseDetail(data);
  expect(result.kind === 'ok' && result.body.professor).toEqual([]);
});
