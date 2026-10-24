import { expect, it } from 'vitest';
import { searchFixture } from '../fixtures/searchDemo';
import { parseChatMeta, requisiteYearsLine } from './chatMeta';
import { parsePlanContext } from './planContext';
import {
  parseReceipt,
  verifiedReceipt,
  feedbackResponseMatches,
} from './answerFeedback';
import { isChatFailure } from './chatFailure';

export function rawMeta(name = 'alias-cs-6140') {
  const e = searchFixture(name).events.find((e) => e.type === 'meta');
  if (e?.type !== 'meta') throw Error('Fixture');
  return structuredClone(e.meta) as Record<string, unknown>;
}
export function setPath(value: unknown, path: string, replacement: unknown) {
  const keys = path.split('.');
  let current = value as Record<string, unknown>;
  for (const key of keys.slice(0, -1))
    current = current[key] as Record<string, unknown>;
  current[keys.at(-1)!] = replacement;
}
it.each([
  ['matched_via', 1],
  ['results', null],
  ['results', {}],
  ['results.0', null],
  ['results.0', []],
  ...['course_id', 'primary_code', 'primary_name'].flatMap((key) =>
    ['', 1, null].map((v) => [`results.0.${key}`, v]),
  ),
  ...[Infinity, NaN, '1', null].map((v) => ['results.0.score', v]),
] as [string, unknown][])(
  'meta rejects only the complete result block for bad %s',
  (path, bad) => {
    const data = rawMeta();
    expect(parseChatMeta(data).kind).toBe('ok');
    setPath(data, path, bad);
    expect(parseChatMeta(data)).toEqual({ kind: 'invalid' });
  },
);
it('meta permits unknown routes, negative scores and extras, but not sparse results', () => {
  const data = rawMeta();
  data.matched_via = 'new-route';
  data.extra = true;
  setPath(data, 'results.0.score', -0);
  expect(parseChatMeta(data).kind).toBe('ok');
  data.results = new Array(1);
  expect(parseChatMeta(data).kind).toBe('invalid');
});
function edition(year = '2026-2027') {
  return {
    catalog_year: year,
    catalog_url: 'https://catalog.northeastern.edu/course-descriptions/cs/',
    captured_at: '2026-09-29T00:00:00Z',
    prerequisite: { status: 'parsed' },
    corequisite: { status: 'not_listed' },
  };
}
function years() {
  return {
    storage: 'available',
    editions: [edition()],
    editions_omitted: 0,
    unusable_records: 0,
    selected_year: null,
    other_years_recorded: 0,
  };
}
const yearBad: [string, unknown][] = [
  ['storage', { toString: null }],
  ['editions.0.prerequisite.status', { toString: null }],
  ['storage', 'other'],
  ['storage', null],
  ['editions', {}],
  ['editions', null],
  ['editions.0', []],
  ['editions.0.catalog_year', '2026/2027'],
  ['editions.0.catalog_year', '2026-2027\n'],
  [
    'editions.0.catalog_url',
    'http://catalog.northeastern.edu/course-descriptions/cs/',
  ],
  [
    'editions.0.catalog_url',
    'https://catalog.northeastern.edu/course-descriptions/cs/#x',
  ],
  [
    'editions.0.catalog_url',
    'https://catalog.northeastern.edu.evil.test/course-descriptions/cs/',
  ],
  ['editions.0.captured_at', '2026-02-30T00:00Z'],
  ['editions.0.captured_at', null],
  ['editions.0.prerequisite', null],
  ['editions.0.corequisite', []],
  ['editions.0.prerequisite.status', 'other'],
  ['editions.0.corequisite.status', 1],
  ...['editions_omitted', 'unusable_records', 'other_years_recorded'].flatMap(
    (key) => [-1, 0.5, '0', null].map((v): [string, unknown] => [key, v]),
  ),
  ['selected_year', '2026-2028'],
  ['selected_year', '2026/2027'],
  ['selected_year', 2026],
];
it.each(yearBad)(
  'requisite year malformed field %s suppresses only the year line',
  (path, bad) => {
    const data = years();
    expect(requisiteYearsLine(data)).not.toBeNull();
    setPath(data, path, bad);
    expect(requisiteYearsLine(data)).toBeNull();
  },
);
it('requisite year independent maximum, descending and unique constraints', () => {
  const data = {
    ...years(),
    editions: [edition(), edition('2025-2026'), edition('2024-2025')],
  };
  expect(requisiteYearsLine(data)).not.toBeNull();
  expect(
    requisiteYearsLine({
      ...data,
      editions: [...data.editions, edition('2023-2024')],
    }),
  ).toBeNull();
  expect(
    requisiteYearsLine({ ...data, editions: [edition(), edition()] }),
  ).toBeNull();
  expect(
    requisiteYearsLine({ ...data, editions: [...data.editions].reverse() }),
  ).toBeNull();
});
it.each(['schema_missing', 'schema_unusable'])(
  'requisite year unavailable storage invariants %s',
  (storage) => {
    const data = { ...years(), storage, editions: [] };
    expect(requisiteYearsLine(data)).toBeNull();
    // Valid empty storage is distinguishable from the same shape being rejected only through the UI;
    // positive controls below independently allow the corresponding nonempty available bundle.
    expect(requisiteYearsLine({ ...data, editions: [edition()] })).toBeNull();
    expect(requisiteYearsLine({ ...data, editions_omitted: 1 })).toBeNull();
    expect(requisiteYearsLine({ ...data, unusable_records: 1 })).toBeNull();
    expect(
      requisiteYearsLine({ ...data, selected_year: '2026-2027' }),
    ).toBeNull();
    expect(
      requisiteYearsLine({
        ...data,
        storage: 'available',
        editions: [edition()],
      }),
    ).not.toBeNull();
  },
);
it('requisite selected-year cardinality, omitted count and other-year invariants have valid controls', () => {
  const selected = {
    ...years(),
    selected_year: '2026-2027',
    other_years_recorded: 4,
  };
  expect(requisiteYearsLine(selected)).toContain('另有 4 个其他年份');
  expect(
    requisiteYearsLine({
      ...selected,
      editions: [edition(), edition('2025-2026')],
    }),
  ).toBeNull();
  expect(requisiteYearsLine({ ...selected, editions_omitted: 1 })).toBeNull();
  const other = {
    ...years(),
    selected_year: '2023-2024',
    editions: [edition(), edition('2025-2026'), edition('2024-2025')],
    editions_omitted: 1,
    other_years_recorded: 4,
  };
  expect(requisiteYearsLine(other)).toContain('展示的其他年份不能替代');
  expect(requisiteYearsLine({ ...other, other_years_recorded: 5 })).toBeNull();
  expect(
    requisiteYearsLine({
      ...other,
      selected_year: null,
      other_years_recorded: 0,
    }),
  ).toContain('另有 1 个更早年份');
  expect(
    requisiteYearsLine({
      ...other,
      selected_year: null,
      other_years_recorded: 1,
    }),
  ).toBeNull();
  expect(
    requisiteYearsLine({
      ...other,
      selected_year: null,
      other_years_recorded: 0,
      editions: other.editions.slice(0, 2),
    }),
  ).toBeNull();
  expect(
    requisiteYearsLine({
      ...years(),
      selected_year: '2023-2024',
      editions: [],
      other_years_recorded: 0,
    }),
  ).toBe('所选方案 Catalog 2023-2024 没有可用的课程块规则。');
});
it('requisite missing counters and editions default, extras and undisplayed rules do not add validation', () => {
  expect(requisiteYearsLine({ storage: 'available' })).toBeNull();
  expect(
    requisiteYearsLine({
      storage: 'available',
      editions: [edition()],
      future: true,
    }),
  ).not.toBeNull();
  expect(requisiteYearsLine(null)).toBeNull();
  expect(requisiteYearsLine([])).toBeNull();
});
export function planInput() {
  const meta = rawMeta('plan-ds-align');
  return {
    plan: meta.plan_context as Record<string, unknown>,
    ids: (meta.results as { course_id: string }[]).map((r) => r.course_id),
  };
}
const firstEntry = (plan: Record<string, unknown>) =>
  Object.keys(plan.placements as object).find(
    (k) => ((plan.placements as Record<string, unknown[]>)[k]?.length ?? 0) > 0,
  )!;
const planBad: [string, unknown][] = [
  ['program_id', ''],
  ['program_id', 'Upper'],
  ['program_id', 1],
  ['program_id', 'x'.repeat(65)],
  ['plan_id', ''],
  ['plan_id', 'x'.repeat(101)],
  ['campus', '1-boston'],
  ['campus', 'x'.repeat(41)],
  ['catalog_year', '2026-2028'],
  ['catalog_year', '2026-2027\n'],
  ['pathway', 'other'],
  ['concentration', ''],
  ['concentration', '   '],
  ['concentration', '😀'.repeat(101)],
  ['plan_content_sha256', 'a'.repeat(63)],
  ['plan_content_sha256', 'A'.repeat(64)],
  ['plan_content_sha256', 'a'.repeat(64) + '\n'],
  ['coverage', 'unknown'],
  ['review_status', 'draft'],
  ['checked_on', '2026-02-30'],
  ['captured_on', null],
  ['source_catalog_year', '2020-2021'],
  ['source_url', 'https://example.com/graduate/x/'],
  ['source_url', 'http://catalog.northeastern.edu/graduate/x/'],
  ['source_url', 'https://catalog.northeastern.edu/graduate/x/?x=1'],
  ['source_url', 'https://catalog.northeastern.edu/graduate/x/\n'],
  ['placements', []],
  ['placements_omitted', []],
];
it.each(planBad)(
  'plan malformed %s hides the entire context with a valid control',
  (path, bad) => {
    const { plan, ids } = planInput();
    expect(parsePlanContext(plan, ids)).not.toBeNull();
    setPath(plan, path, bad);
    expect(parsePlanContext(plan, ids)).toBeNull();
  },
);
const entryBad: [string, unknown][] = [
  ['path', []],
  ['path', Array(9).fill('x')],
  ['path', ['']],
  ['path', ['x'.repeat(301)]],
  ['path', [1]],
  ['relation', 'other'],
  ['under_any_of', 1],
  ['under_any_of', null],
  ['activate_when', null],
  ['activate_when', ['   ']],
  ['activate_when', ['x'.repeat(501)]],
  ['activate_when', Array(9).fill('x')],
  ['areas', null],
  ['areas', ['']],
  ['areas', ['x'.repeat(301)]],
  ['areas', Array(41).fill('x')],
  ...[
    ['min_courses', 100],
    ['min_credits', 200],
    ['min_areas', 40],
  ].flatMap(([k, bound]) =>
    [0, Number(bound) + 1, 1.5, '1'].map((v): [string, unknown] => [
      String(k),
      v,
    ]),
  ),
];
it.each(entryBad)(
  'plan placement malformed %s hides the complete block',
  (path, bad) => {
    const { plan, ids } = planInput();
    expect(parsePlanContext(plan, ids)).not.toBeNull();
    setPath(plan, `placements.${firstEntry(plan)}.0.${path}`, bad);
    expect(parsePlanContext(plan, ids)).toBeNull();
  },
);
it('plan dates, archive-year consistency and matched placement keys are independent', () => {
  const { plan, ids } = planInput();
  plan.checked_on = '2024-02-29';
  plan.captured_on = '2024-02-29';
  expect(parsePlanContext(plan, ids)).not.toBeNull();
  plan.checked_on = '2024-02-28';
  expect(parsePlanContext(plan, ids)).toBeNull();
  plan.checked_on = '2024-02-29';
  plan.source_url = `https://catalog.northeastern.edu/archive/${plan.catalog_year}/graduate/x/`;
  expect(parsePlanContext(plan, ids)).not.toBeNull();
  plan.source_url =
    'https://catalog.northeastern.edu/archive/2020-2021/graduate/x/';
  expect(parsePlanContext(plan, ids)).toBeNull();
  plan.source_url = 'https://catalog.northeastern.edu/graduate/x/';
  expect(parsePlanContext(plan, [...ids].reverse())).not.toBeNull();
  expect(
    parsePlanContext(plan, ['unknown-course', ...ids.slice(1)]),
  ).toBeNull();
  expect(parsePlanContext(plan, [...ids, 'extra-course'])).toBeNull();
  expect(parsePlanContext(plan, ids.slice(1))).toBeNull();
  (plan.placements_omitted as Record<string, unknown>).extra = 0;
  expect(parsePlanContext(plan, ids)).toBeNull();
});
it('plan entry and collection bounds accept exact limits and optional defaults', () => {
  const { plan, ids } = planInput();
  const entries = plan.placements as Record<string, unknown[]>;
  const key = firstEntry(plan),
    entry = entries[key]![0] as Record<string, unknown>;
  entry.path = Array(8).fill('😀'.repeat(300));
  entry.areas = Array(40).fill('x');
  entry.activate_when = Array(8).fill('😀'.repeat(500));
  entry.min_courses = 100;
  entry.min_credits = 200;
  entry.min_areas = 40;
  entries[key] = Array(4).fill(entry);
  expect(parsePlanContext(plan, ids)).not.toBeNull();
  entries[key] = Array(5).fill(entry);
  expect(parsePlanContext(plan, ids)).toBeNull();
  entries[key] = [entry];
  for (const field of [
    'under_any_of',
    'activate_when',
    'areas',
    'min_courses',
    'min_credits',
    'min_areas',
  ])
    delete entry[field];
  expect(parsePlanContext(plan, ids)).not.toBeNull();
  for (const relation of [
    'required',
    'any_of_option',
    'select_candidate',
    'optional_branch',
    'excluded',
    'open_pool',
  ]) {
    entry.relation = relation;
    expect(parsePlanContext(plan, ids)).not.toBeNull();
  }
  const manyIds = Array.from({ length: 20 }, (_, n) => `c-${n}`);
  plan.placements = Object.fromEntries(manyIds.map((id) => [id, []]));
  plan.placements_omitted = Object.fromEntries(manyIds.map((id) => [id, 0]));
  expect(parsePlanContext(plan, manyIds)).not.toBeNull();
  (plan.placements as Record<string, unknown>).extra = [];
  (plan.placements_omitted as Record<string, unknown>).extra = 0;
  expect(parsePlanContext(plan, [...manyIds, 'extra'])).toBeNull();
});
it.each([-1, 0.5, '0'])(
  'plan omitted counts reject %s without key mismatch masking',
  (bad) => {
    const { plan, ids } = planInput();
    expect(parsePlanContext(plan, ids)).not.toBeNull();
    (plan.placements_omitted as Record<string, unknown>)[ids[0]!] = bad;
    expect(parsePlanContext(plan, ids)).toBeNull();
  },
);
function receipt() {
  const e = searchFixture('feedback-receipt').events.find(
    (e) => e.type === 'done',
  );
  if (e?.type !== 'done') throw Error('fixture');
  return structuredClone(e.feedback) as Record<string, unknown>;
}
it.each([
  ['answer_id', 'a'.repeat(31)],
  ['answer_id', 'A'.repeat(32)],
  ['answer_id', 'a'.repeat(32) + '\n'],
  ['answer_id', 1],
  ['answer_sha256', 'a'.repeat(63)],
  ['answer_sha256', 'A'.repeat(64)],
  ['answer_sha256', null],
  ['feedback_token', 'a'.repeat(42)],
  ['feedback_token', '+'.repeat(43)],
  ['feedback_token', 'a'.repeat(43) + '\n'],
  ['extra', true],
] as [string, unknown][])(
  'receipt rejects %s and never loosely validates extra keys',
  (field, bad) => {
    const r = receipt();
    expect(parseReceipt(r)).not.toBeNull();
    r[field] = bad;
    expect(parseReceipt(r)).toBeNull();
  },
);
it('receipt is bound to exact UTF-8 text, not trimmed text, partial text or a different answer', async () => {
  const r = receipt(),
    text = searchFixture('feedback-receipt')
      .events.filter((e) => e.type === 'token')
      .map((e) => e.text)
      .join('');
  expect(await verifiedReceipt(text, r)).toEqual(r);
  expect(await verifiedReceipt(text + ' ', r)).toBeNull();
  expect(await verifiedReceipt(text.slice(1), r)).toBeNull();
  expect(await verifiedReceipt('   ', r)).toBeNull();
  const unicode = '😀中文\r\n';
  const digest = await crypto.subtle.digest(
    'SHA-256',
    new TextEncoder().encode(unicode),
  );
  r.answer_sha256 = [...new Uint8Array(digest)]
    .map((n) => n.toString(16).padStart(2, '0'))
    .join('');
  expect(await verifiedReceipt(unicode, r)).toEqual(r);
});
it('feedback response requires exactly own keys, matching answer ID and clicked rating', () => {
  const vote = { ...parseReceipt(receipt())!, rating: 'up' as const };
  const ok = { answer_id: vote.answer_id, rating: 'up' };
  expect(feedbackResponseMatches(ok, vote)).toBe(true);
  for (const value of [
    null,
    [],
    {},
    { ...ok, extra: true },
    { ...ok, rating: 'down' },
    { ...ok, answer_id: 'other' },
    Object.assign(Object.create(ok) as object, { a: 1, b: 2 }),
  ])
    expect(feedbackResponseMatches(value, vote)).toBe(false);
  expect(
    parseReceipt(
      Object.assign(Object.create(receipt()) as object, { a: 1, b: 2, c: 3 }),
    ),
  ).toBeNull();
});
it('receipt rejects comma-containing own keys that alias the expected key list', () => {
  const valid = receipt();
  expect(parseReceipt(valid)).not.toBeNull();
  const aliased = Object.assign(Object.create(valid) as object, {
    'answer_id,answer_sha256': null,
    feedback_token: valid.feedback_token,
  });
  expect(parseReceipt(aliased)).toBeNull();
});
it('feedback response rejects comma-containing own keys that alias the expected key list', () => {
  const vote = { ...parseReceipt(receipt())!, rating: 'up' as const };
  const valid = { answer_id: vote.answer_id, rating: vote.rating };
  expect(feedbackResponseMatches(valid, vote)).toBe(true);
  const aliased = Object.assign(Object.create(valid) as object, {
    'answer_id,rating': null,
  });
  expect(feedbackResponseMatches(aliased, vote)).toBe(false);
});
it('ChatFailure permits class instances but rejects incomplete or malformed fields', () => {
  const ok = {
    status: 404,
    errorType: null,
    reason: null,
    retryAfter: null,
    invalidFields: [],
  };
  expect(isChatFailure(ok)).toBe(true);
  for (const [key, value] of Object.entries({
    status: 99,
    errorType: 1,
    reason: 1,
    retryAfter: '1',
    invalidFields: [null],
  }))
    expect(isChatFailure({ ...ok, [key]: value })).toBe(false);
  expect(isChatFailure({ ...ok, status: 600 })).toBe(false);
  expect(isChatFailure({ ...ok, status: 200.5 })).toBe(false);
});
