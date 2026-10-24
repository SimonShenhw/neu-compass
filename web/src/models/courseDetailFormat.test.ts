import { expect, it } from 'vitest';
import {
  confidenceEven,
  evidenceValue,
  FIELD_LABELS,
  labelFor,
  noticeLine,
  oneLine,
  OVERVIEW_EXCLUDED,
  percentEven,
  pyG,
  snapshotDigest,
  sourceKind,
  sourceSummary,
  utcMinute,
  WARNING_LABELS,
} from './courseDetailFormat';

it.each([
  [0, '0'],
  [-0, '-0'],
  [7.5, '7.5'],
  [12, '12'],
  [4, '4'],
  [4.25, '4.25'],
  [12.3456789, '12.3457'],
  [100000, '100000'],
  [1234567, '1.23457e+06'],
  [0.0001, '0.0001'],
  [0.00001, '1e-05'],
  [999999.5, '1e+06'],
  [0.000123456789, '0.000123457'],
  [123456.5, '123456'],
  [123457.5, '123458'],
  [9.999995e-5, '0.0001'],
  [1e-100, '1e-100'],
  [-12.3456789, '-12.3457'],
] as const)(
  'pyG exact six-digit Python formatting %s -> %s',
  (value, expected) => expect(pyG(value)).toBe(expected),
);
it.each([
  [0, '0.00'],
  [-0, '-0.00'],
  [0.005, '0.01'],
  [0.015, '0.01'],
  [0.025, '0.03'],
  [0.035, '0.04'],
  [0.045, '0.04'],
  [0.055, '0.06'],
  [0.065, '0.07'],
  [0.075, '0.07'],
  [0.085, '0.09'],
  [0.095, '0.10'],
  [0.125, '0.12'],
  [0.375, '0.38'],
  [0.5, '0.50'],
  [0.875, '0.88'],
  [0.995, '0.99'],
  [0.9999, '1.00'],
  [1, '1.00'],
  [0.12499999999999999, '0.12'],
  [0.12500000000000003, '0.13'],
  [0.37499999999999994, '0.37'],
  [0.37500000000000006, '0.38'],
  [0.8749999999999999, '0.87'],
  [0.8750000000000001, '0.88'],
] as const)(
  'confidence exact binary half-even Python oracle %s -> %s',
  (value, expected) => expect(confidenceEven(value)).toBe(expected),
);
it.each([
  [0.125, '12'],
  [0.575, '57'],
  [0.005, '0'],
  [0.025, '2'],
  [0.375, '38'],
  [0.875, '88'],
  [0, '0'],
  [-0, '-0'],
  [1, '100'],
] as const)(
  'percentage multiplies first then rounds even %s -> %s',
  (value, expected) => expect(percentEven(value)).toBe(expected),
);
it.each([
  ['2026-09-29T03:00:15Z', '2026-09-29 03:00 UTC'],
  ['2026-09-29T08:30:00+05:00', '2026-09-29 03:30 UTC'],
  ['2026-09-29T23:30:00-05:00', '2026-09-30 04:30 UTC'],
  ['2026-01-01T00:15:59.123456+02:30', '2025-12-31 21:45 UTC'],
  ['2026-12-31T23:59:59-00:30', '2027-01-01 00:29 UTC'],
  ['2026-09-29T03:00:00', '2026-09-29 03:00'],
  ['2026-09-29 03:00', '2026-09-29 03:00'],
] as const)(
  'UTC minute conversion and naive preservation %s',
  (value, expected) => expect(utcMinute(value)).toBe(expected),
);
it.each([
  '2026-02-30T03:00:00Z',
  '2025-02-29T00:00Z',
  '2026-01-01T24:00Z',
  '2026-01-01T00:00+24:00',
  '2026-01-01T00:00+02:60',
  'not-time',
])('invalid ISO timestamp is rejected %s', (value) =>
  expect(() => utcMinute(value)).toThrow(),
);
it('snapshot digest accepts only a complete lowercase 64-hex catalog ID', () => {
  const digest = 'a'.repeat(64);
  expect(snapshotDigest('catalog:' + digest)).toBe(digest);
  for (const id of [
    'catalog:' + digest + '\n',
    'catalog:' + digest.toUpperCase(),
    'catalog:' + digest.slice(1),
    'other:' + digest,
    '',
  ])
    expect(snapshotDigest(id)).toBeNull();
});
it('source summary deduplicates IDs and keeps first-seen order for tied counts', () => {
  const ids = [
    'reddit_a',
    'rmp_review_a',
    'syllabus_a',
    'rmp_review_b',
    'reddit_a',
    'catalog_a',
    'synthetic_seed_a',
    'forum_a',
  ];
  expect(sourceSummary(ids)).toBe(
    'RateMyProfessors 教师评价 2 条、Reddit 讨论 1 条、课程大纲 1 条、抽取时用的课程文本 1 条、合成测试数据 1 条、其他来源 1 条',
  );
  expect(sourceSummary(['reddit_a', 'rmp_review_a'])).toBe(
    'Reddit 讨论 1 条、RateMyProfessors 教师评价 1 条',
  );
  expect(sourceKind('prefix_reddit_a')).toBe('其他来源');
  expect(sourceKind('rmp_review')).toBe('其他来源');
  expect(sourceSummary([])).toBe('');
});
it('notice filters exclusions and unknowns while retaining first-seen known order exactly once', () => {
  expect(
    noticeLine([
      'topics_source_unavailable',
      'constructor',
      'topics_source_unavailable',
      'catalog_metadata_conflict',
    ]),
  ).toBe('主题列表没有来源；目录学分和课程记录不一致，请向学校核实。');
  expect(
    noticeLine(
      [
        'catalog_source_unavailable',
        'requisites_differ_by_catalog_year',
        'requisite_clause_unparsed',
        'structured_requisites_unusable',
      ],
      OVERVIEW_EXCLUDED,
    ),
  ).toBeNull();
  expect(noticeLine(['unknown', '__proto__'])).toBeNull();
  expect(Object.keys(WARNING_LABELS)).toHaveLength(13);
  expect(Object.keys(FIELD_LABELS)).toHaveLength(12);
  expect(labelFor(FIELD_LABELS, 'constructor')).toBe('constructor');
  expect(labelFor(WARNING_LABELS, '__proto__')).toBe('__proto__');
});
it('Python splitlines normalization preserves blanks and removes only the terminal separator', () => {
  expect(oneLine('a\n')).toBe('a');
  expect(oneLine('a\n\nb')).toBe('a  b');
  expect(oneLine('a\r\x1cb')).toBe('a  b');
  expect(oneLine(' a \r\nb ')).toBe(' a  b ');
  expect(oneLine('a\r\nb\rc\vd\fe\x1cf\x1dg\x1eh\x85i\u2028j\u2029k')).toBe(
    'a b c d e f g h i j k',
  );
  expect(oneLine('a\n\n')).toBe('a ');
  expect(oneLine('')).toBe('');
});
it.each([
  ['literal\ntext', 'literal\ntext'],
  [4.0, '4'],
  [true, 'true'],
  [null, 'null'],
  [['a', 'b'], 'a、b'],
  [{ a: 'x' }, '{"a":"x"}'],
  [['a', 1, null], '["a",1,null]'],
  [[], ''],
] as const)(
  'evidence values use the explicit JS display contract for %j',
  (value, expected) => expect(evidenceValue(value)).toBe(expected),
);
