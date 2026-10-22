import { expect, it } from 'vitest';
import fixture from '../fixtures/compare/course-cs-5800.json';
import {
  BAD_CELL,
  NO_RULES,
  courseHeader,
  creditRangeNote,
  deepEqual,
  detailCell,
  generalNumber,
  gradingText,
  noticeLine,
  requisiteSummary,
  when,
} from './compare';
import type { JsonObject } from './compare';

const base = fixture.body;
const sec = (
  status = 'not_listed',
  rule: unknown = null,
  raw_text: string | null = null,
) => ({ status, rule, raw_text });
function doc(
  year = '2026-2027',
  prerequisite = sec(),
  corequisite = sec(),
  extra: JsonObject = {},
) {
  return {
    course_id: base.course_id,
    course_code: base.primary_code,
    course_name: base.primary_name,
    catalog_year: year,
    credit_hours: { kind: 'fixed', raw_text: '4 Hours' },
    requisites: { prerequisite, corequisite },
    ...extra,
  };
}
const course = (documents: unknown[], extra: JsonObject = {}): JsonObject => ({
  ...base,
  course_requisites: {
    schema_available: true,
    documents,
    unusable_records: 0,
    warnings: [],
    ...extra,
  },
});
const lines = (row: Parameters<typeof detailCell>[0], body: JsonObject) =>
  detailCell(row, body).lines.map((line) => line.text);
const different = '这些年度已记录的条款不同，请按适用年度核对。';

it('no annual rules for null or absent bundle, not for legacy flat prerequisite codes', () => {
  expect(requisiteSummary({ ...base, course_requisites: null })).toEqual([
    NO_RULES,
  ]);
  const missing: JsonObject = { ...base };
  delete missing.course_requisites;
  expect(requisiteSummary(missing)).toEqual([NO_RULES]);
});
it.each([
  { documents: ['bad'] },
  {
    schema_available: true,
    documents: [doc()],
    unusable_records: -1,
    warnings: [],
  },
  {
    schema_available: 'true',
    documents: [],
    unusable_records: 0,
    warnings: [],
  },
  {
    schema_available: true,
    documents: [doc('2026')],
    unusable_records: 0,
    warnings: [],
  },
  {
    schema_available: true,
    documents: [doc('2026-2027', sec('unknown'))],
    unusable_records: 0,
    warnings: [],
  },
])('malformed requisite listing %j fails closed', (data) => {
  expect(requisiteSummary({ ...base, course_requisites: data })).toEqual([
    '年度规则没有通过校验，暂不显示；不表示没有先修或共修要求。',
  ]);
  expect(creditRangeNote({ ...base, course_requisites: data })).toBeNull();
});
it('unavailable requisite schema short circuits all partial records', () => {
  expect(
    requisiteSummary(
      course([doc()], { schema_available: false, unusable_records: 1 }),
    ),
  ).toEqual(['结构化先修规则暂时不可用；不表示没有先修或共修要求。']);
});
it.each([
  { unusable_records: 1 },
  { warnings: ['structured_requisite_schema_unusable'] },
])('unusable storage notice is first: %j', (extra) => {
  expect(requisiteSummary(course([doc()], extra))[0]).toBe(
    '存在不可用记录或存储结构；不能据此确认完整要求。',
  );
});
it.each(['course_id', 'course_code', 'course_name'])(
  'foreign %s documents are excluded before comparing years',
  (key) => {
    const result = requisiteSummary(
      course([doc(), doc('2025-2026', sec(), sec(), { [key]: 'foreign' })]),
    );
    expect(result[0]).toBe('有课程身份不符的年度记录，未用于比较。');
    expect(result).toContain('已记录 Catalog 年份：2026-2027');
    expect(result).toContain('只记录了一个年度，不能跨年比较。');
  },
);
it('no own documents keeps identity mismatch notice then no rules', () => {
  expect(
    requisiteSummary(
      course([doc('2026-2027', sec(), sec(), { course_id: 'other' })]),
    ),
  ).toEqual(['有课程身份不符的年度记录，未用于比较。', NO_RULES]);
});
it('duplicate years are not arbitrarily selected', () => {
  const body = course([doc(), doc()]);
  expect(requisiteSummary(body)).toEqual([
    '同年度有冲突记录，未任取一份比较。',
  ]);
  expect(creditRangeNote(body)).toBeNull();
});
it('one year is explicitly not cross-year evidence', () => {
  expect(requisiteSummary(course([doc()]))).toEqual([
    '已记录 Catalog 年份：2026-2027',
    '只记录了一个年度，不能跨年比较。',
    '未列出或未解析的条款仍未知；不判断个人适用年度或能否注册。',
  ]);
});
it('middle year difference is compared across all documents, not just newest and oldest', () => {
  const normal = sec('parsed', { op: 'all', children: [{ code: 'CS 5800' }] });
  const changed = sec('parsed', { op: 'any', children: [{ code: 'CS 5800' }] });
  expect(
    requisiteSummary(
      course([
        doc('2026-2027', normal),
        doc('2025-2026', changed),
        doc('2024-2025', normal),
      ]),
    ),
  ).toContain(different);
});
it('unparsed text is compared in full beyond any display cutoff', () => {
  const prefix = '共同原文'.repeat(200);
  expect(
    requisiteSummary(
      course([
        doc('2026-2027', sec('unparsed', null, prefix + 'A')),
        doc('2025-2026', sec('unparsed', null, prefix + 'B')),
      ]),
    ),
  ).toContain(different);
});
it('corequisites are compared even when prerequisites match', () => {
  expect(
    requisiteSummary(
      course([
        doc(),
        doc('2025-2026', sec(), sec('parsed', { code: 'CS 6140' })),
      ]),
    ),
  ).toContain(different);
});
it('parsed rule tree, not its raw wording or object-key order, controls equality', () => {
  const a = sec(
    'parsed',
    { op: 'all', children: [{ code: 'CS 5800', grade: 'C' }] },
    'first wording',
  );
  const b = sec(
    'parsed',
    { children: [{ grade: 'C', code: 'CS 5800' }], op: 'all' },
    'different wording',
  );
  expect(
    requisiteSummary(course([doc('2026-2027', a), doc('2025-2026', b)])),
  ).toContain('这些年度已记录的条款结构相同。');
  expect(
    deepEqual({ op: 'all', children: [1, 2] }, { op: 'all', children: [2, 1] }),
  ).toBe(false);
});
it('credit range uses newest own year and never foreign or duplicate years', () => {
  const range = { credit_hours: { kind: 'range', raw_text: '1-4 Hours' } };
  expect(
    creditRangeNote(
      course([doc('2026-2027', sec(), sec(), range), doc('2025-2026')]),
    ),
  ).toBe('2026-2027 目录标题学分：1-4 Hours；实际班次学分未声明。');
  expect(
    creditRangeNote(
      course([
        doc(),
        doc('2027-2028', sec(), sec(), { ...range, course_code: 'DS 5220' }),
      ]),
    ),
  ).toBeNull();
  expect(
    creditRangeNote(course([doc(), doc('2025-2026', sec(), sec(), range)])),
  ).toBeNull();
  expect(
    creditRangeNote(course([doc('2026-2027', sec(), sec(), range), doc()])),
  ).toBeNull();
});
it('percentages use half-even rounding and missing weights stay names only', () => {
  expect(
    gradingText([
      { name: 'A', weight: 0.125 },
      { name: 'B', weight: 0.375 },
      { name: 'C', weight: 0.135 },
      { name: 'Participation', weight: null },
    ]),
  ).toBe('A 12% · B 38% · C 14% · Participation');
});
it.each([
  [12, '12'],
  [12.5, '12.5'],
  [3.75, '3.75'],
  [123456.5, '123456'],
  [123457.5, '123458'],
  [1e-5, '1e-05'],
  [1e6, '1e+06'],
  [0.0001, '0.0001'],
  [1.23456789, '1.23457'],
  [0, '0'],
])('Python general-number formatting %s -> %s', (n, text) => {
  expect(generalNumber(n as number)).toBe(text);
});
it('estimates preserve zero workload and do not invent zero difficulty', () => {
  expect(
    lines('学生评价里的估计', {
      ...base,
      workload_hours_per_week: 0,
      difficulty_score: null,
    })[0],
  ).toBe('每周约 0 小时');
});
it.each([
  { catalog_url: 'https://elsewhere.example/course-descriptions/cs/' },
  {
    course_code: 'DS 5220',
    catalog_url: 'https://catalog.northeastern.edu/course-descriptions/cs/',
  },
  { extra: 'not allowed' },
  {
    catalog_url: 'https://catalog.northeastern.edu/course-descriptions/cs/?x=1',
  },
  { imported_at: '2026-02-30T14:00:00Z' },
  { credits: 1.5 },
  { prereq_codes: [5] },
])('catalog validation rejects unsafe source/shape %j', (change) => {
  const cell = detailCell('官方目录描述', {
    ...base,
    answer_evidence: {
      ...base.answer_evidence,
      catalog: { ...base.answer_evidence.catalog, ...change },
    },
  });
  expect(cell.lines[0]?.text).toBe(
    '目录存档没有通过格式或来源校验，所以不显示描述和链接。',
  );
  expect(cell.lines.some((line) => line.catalogUrl)).toBe(false);
  expect(cell.lines.some((line) => line.text.includes('目录抓取：'))).toBe(
    false,
  );
  expect(
    cell.lines.some(
      (line) => line.text === base.answer_evidence.catalog.description,
    ),
  ).toBe(false);
});
it('catalog code normalization retains only matching exact official links', () => {
  expect(
    detailCell('官方目录描述', {
      ...base,
      answer_evidence: {
        ...base.answer_evidence,
        catalog: { ...base.answer_evidence.catalog, course_code: ' cs5800 ' },
      },
    }).lines.some(
      (line) => line.catalogUrl === base.answer_evidence.catalog.catalog_url,
    ),
  ).toBe(true);
});
it('timestamps use UTC for offsets but never add a zone to naive times', () => {
  expect(when('2026-09-28T14:07:00+02:00')).toBe('2026-09-28 12:07 UTC');
  expect(when('2026-09-28T14:07:00')).toBe('2026-09-28 14:07');
  expect(when('2026-09-28T14:07:00Z')).toBe('2026-09-28 14:07 UTC');
});
it('null evidence is unknown; malformed evidence damages only evidence-dependent cells', () => {
  expect(lines('官方目录描述', { ...base, answer_evidence: null })).toEqual([
    '目录存档情况没有记录。',
  ]);
  expect(lines('缺的数据', { ...base, answer_evidence: null })).toEqual([
    '缺失字段没有记录；不表示数据齐全。',
  ]);
  expect(lines('官方目录描述', { ...base, answer_evidence: [] })).toEqual([
    BAD_CELL,
  ]);
  expect(lines('缺的数据', { ...base, answer_evidence: [] })).toEqual([
    BAD_CELL,
  ]);
  expect(lines('考核构成', { ...base, answer_evidence: [] })).not.toContain(
    BAD_CELL,
  );
});
it.each(['topics_covered', 'grading_components', 'program_context'])(
  'bad %s types remain isolated to their cell',
  (key) => {
    const row = {
      topics_covered: '主题',
      grading_components: '考核构成',
      program_context: '在培养方案里的位置',
    }[key] as Parameters<typeof detailCell>[0];
    expect(lines(row, { ...base, [key]: 'wrong' })).toEqual([BAD_CELL]);
    expect(lines('官方目录描述', { ...base, [key]: 'wrong' })[0]).toBe(
      base.answer_evidence.catalog.description,
    );
  },
);
it('unknown requirement types are preserved, not labelled foundation', () => {
  const body = {
    ...base,
    program_context: [
      {
        program_id: 'p',
        program_name: 'Unknown program',
        requirement_type: 'future_code',
        semester_recommended: null,
      },
    ],
  };
  expect(detailCell('在培养方案里的位置', body).programs?.[0]?.label).toBe(
    'future_code',
  );
});
it('unknown missing fields remain literal and empty missing list is not proof of completeness', () => {
  expect(
    lines('缺的数据', {
      ...base,
      answer_evidence: { missing_fields: ['new_field'] },
    })[0],
  ).toBe('缺失：new_field');
  expect(
    lines('缺的数据', { ...base, answer_evidence: { missing_fields: [] } })[0],
  ).toBe('没有列出缺失项；不表示数据齐全');
});
it('notices preserve API order, deduplicate and never echo unknown/prototype codes', () => {
  expect(
    noticeLine([
      'topics_source_unavailable',
      'catalog_metadata_conflict',
      'topics_source_unavailable',
      '__proto__',
      'unknown',
    ]),
  ).toBe('主题列表没有来源；目录学分和课程记录不一致，请向学校核实。');
  expect(noticeLine(['unknown'])).toBeNull();
});
it('header displays zero credits, omits absent metadata and renders future modes literally', () => {
  expect(
    courseHeader({
      ...base,
      term: null,
      credits: 0,
      delivery_mode: 'future_mode',
    })?.metadata,
  ).toEqual([
    { label: '学分', value: '0' },
    { label: '授课方式', value: 'future mode' },
  ]);
  expect(
    courseHeader({ ...base, term: null, credits: null, delivery_mode: null })
      ?.metadata,
  ).toEqual([]);
});
