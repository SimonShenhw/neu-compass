import { expect, it } from 'vitest';
import type { ProgramCurriculum } from '../api/programs';
import { isTransient } from '../api/load';
import { ApiError } from '../api/client';
import { parseProgramList, parseCurriculum } from './programs';
import { parseCoopPreview } from './coopPreview';
import { coopLock, semester1Pick, showLanding, landingText } from './landing';
import { newTurn } from './chatTurn';
import { landingFixture } from '../fixtures/landingDemo';
import picks from '../fixtures/landing/expected/semester1-vectors.json';
import locks from '../fixtures/landing/expected/lock-vectors.json';
import transient from '../fixtures/landing/expected/transient-vectors.json';

const body = (name: string) => structuredClone(landingFixture(name).body);
function edited(
  value: unknown,
  path: readonly (string | number)[],
  bad: unknown,
) {
  const copy = structuredClone(value);
  let at = copy as Record<string | number, unknown>;
  for (const key of path.slice(0, -1))
    at = at[key] as Record<string | number, unknown>;
  at[path.at(-1)!] = bad;
  return copy;
}
it.each(picks)('semester1 reference $name', (v) => {
  expect(
    semester1Pick(v as Pick<ProgramCurriculum, 'semesters'>)?.course_id ?? null,
  ).toBe(v.pick);
});
it.each(locks.map((v, index) => ({ ...v, index })))(
  'Co-op lock reference $index',
  (v) => {
    const parsed = parseCoopPreview([v.row]);
    if (parsed.kind !== 'ok') throw Error('bad reference');
    const lock = coopLock(parsed.data[0]!);
    expect(lock ? `这条有${lock}：你分享的经验公开后解锁` : null).toBe(v.lock);
  },
);
it.each(transient)('transient reference $status', (v) => {
  const fields = {
    status: v.status,
    errorType: null,
    retryAfter: null,
    invalidFields: [],
    reason: null,
  };
  expect(isTransient(fields)).toBe(v.transient);
  expect(isTransient(new ApiError(v.status))).toBe(v.transient);
});
it('landing visibility depends on any turn, including waiting rejected or stopped, not answer text', () => {
  expect(showLanding([])).toBe(true);
  for (const status of [
    'waiting',
    'answering',
    'done',
    'failed',
    'stopped',
  ] as const)
    expect(showLanding([{ ...newTurn(1, 'q', false), status }])).toBe(false);
});
it('landing plain text removes only CR, preserving LF and all other characters', () => {
  expect(landingText('a\r\nb\rc\t  d\u0085')).toBe('a\nbc\t  d\u0085');
});
it.each([null, {}, 'x', [null], Array(1)].map((value) => ({ value })))(
  'program list rejects invalid root or element %#',
  ({ value }) => {
    expect(parseProgramList(body('programs')).kind).toBe('ok');
    expect(parseProgramList(value).kind).toBe('invalid');
  },
);
it.each([
  [['0', 'program_id'], ''],
  [['0', 'program_id'], '😀'.repeat(65)],
  [['0', 'program_id'], 1],
  [['0', 'prefix'], null],
  [['0', 'full_name'], 1],
  [['0', 'course_count'], -1],
  [['0', 'course_count'], true],
  [['0', 'course_count'], 1.5],
  [['0', 'course_count'], Infinity],
  [['0', 'plan_count'], -1],
  [['0', 'plan_count'], '1'],
] as [string[], unknown][])(
  'program list checks each required scalar %#',
  (path, bad) => {
    const valid = body('programs');
    expect(parseProgramList(valid).kind).toBe('ok');
    expect(parseProgramList(edited(valid, path, bad)).kind).toBe('invalid');
  },
);
it('program list rejects duplicate IDs, counts Unicode code points and permits documented empty text and extra keys', () => {
  const list = body('programs') as Record<string, unknown>[];
  list[0]!.program_id = '😀'.repeat(64);
  list[0]!.prefix = '';
  list[0]!.full_name = '';
  list[0]!.extra = true;
  expect(parseProgramList(list).kind).toBe('ok');
  list[1]!.program_id = list[0]!.program_id;
  expect(parseProgramList(list).kind).toBe('invalid');
  expect(parseProgramList([])).toEqual({ kind: 'ok', data: [] });
});
it.each([
  [['program_id'], 'foreign'],
  [['prefix'], null],
  [['full_name'], 1],
  [['notes'], {}],
  [['semesters'], null],
  [['semesters', 0], null],
  [['semesters', 0, 'semester'], true],
  [['semesters', 0, 'semester'], 0],
  [['semesters', 0, 'semester'], 9],
  [['semesters', 0, 'semester'], 1.5],
  [['semesters', 0, 'courses'], null],
  [['semesters', 0, 'courses', 0], []],
  [['semesters', 0, 'courses', 0, 'course_id'], ''],
  [['semesters', 0, 'courses', 0, 'course_id'], 2],
  [['semesters', 0, 'courses', 0, 'primary_code'], null],
  [['semesters', 0, 'courses', 0, 'primary_name'], {}],
  [['semesters', 0, 'courses', 0, 'requirement_type'], 1],
  [['semesters', 0, 'courses', 0, 'notes'], true],
  [['plans'], {}],
  [['plan_schema_available'], 1],
] as [(string | number)[], unknown][])(
  'curriculum checks every root semester and course field %#',
  (path, bad) => {
    const valid = body('curriculum-aai-ms');
    expect(parseCurriculum(valid, 'aai-ms').kind).toBe('ok');
    expect(parseCurriculum(edited(valid, path, bad), 'aai-ms').kind).toBe(
      'invalid',
    );
  },
);
it.each([null, [], 1, 'x'])('curriculum requires an object %#', (v) =>
  expect(parseCurriculum(v, 'aai-ms').kind).toBe('invalid'),
);
it('the documented edges are accepted: a course count of 0 and semester 8', () => {
  expect(
    parseProgramList(edited(body('programs'), [0, 'course_count'], 0)).kind,
  ).toBe('ok');
  expect(
    parseCurriculum(
      edited(body('curriculum-aai-ms'), ['semesters', 1, 'semester'], 8),
      'aai-ms',
    ).kind,
  ).toBe('ok');
});
it('curriculum defaults optional fields, checks all groups and keeps unvalidated plans for R4a', () => {
  const valid = body('curriculum-aai-ms') as Record<string, unknown>;
  delete valid.notes;
  valid.extra = true;
  valid.plans = [null, 'not R3d concern'];
  const groups = valid.semesters as Record<string, unknown>[];
  delete groups[0]!.semester;
  const courses = groups[0]!.courses as Record<string, unknown>[];
  delete courses[0]!.notes;
  const result = parseCurriculum(valid, 'aai-ms');
  expect(result.kind).toBe('ok');
  if (result.kind !== 'ok') throw Error('valid defaults');
  expect(result.data.notes).toBeNull();
  expect(result.data.semesters[0]!.semester).toBeNull();
  expect(result.data.semesters[0]!.courses[0]!.notes).toBeNull();
  expect(result.data.plans).toEqual(valid.plans);
  groups[1]!.courses = [null];
  expect(parseCurriculum(valid, 'aai-ms').kind).toBe('invalid');
});
it.each([
  ['company', null],
  ['role', 1],
  ['visibility_level', true],
  ['visibility_level', -1],
  ['visibility_level', 3],
  ['visibility_level', 0.5],
  ['interview_summary', {}],
  ['technical_questions', []],
  ['salary_range_usd', 1],
] as [string, unknown][])('Co-op preview checks %s %#', (field, bad) => {
  const valid = body('coop-guest');
  expect(parseCoopPreview(valid).kind).toBe('ok');
  expect(parseCoopPreview(edited(valid, [0, field], bad)).kind).toBe('invalid');
});
it.each(
  [null, {}, 'x', [null], [[], null], Array(1)].map((value) => ({ value })),
)('Co-op preview rejects invalid root or first two rows %#', ({ value }) =>
  expect(parseCoopPreview(value).kind).toBe('invalid'),
);
it('Co-op preview defaults optional strings, ignores unknown fields and never validates the third row', () => {
  const value = body('coop-guest') as Record<string, unknown>[];
  for (const key of [
    'interview_summary',
    'technical_questions',
    'salary_range_usd',
  ])
    delete value[0]![key];
  value[0]!.extra = true;
  value.push(null as unknown as Record<string, unknown>);
  const parsed = parseCoopPreview(value);
  expect(parsed.kind).toBe('ok');
  if (parsed.kind !== 'ok') throw Error('first two valid');
  expect(parsed.data).toHaveLength(2);
  expect(parsed.data[0]!.interview_summary).toBeNull();
  value[1]!.company = null;
  expect(parseCoopPreview(value).kind).toBe('invalid');
  expect(parseCoopPreview([])).toEqual({ kind: 'ok', data: [] });
});
