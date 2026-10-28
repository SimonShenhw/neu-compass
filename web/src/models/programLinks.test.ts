import { describe, expect, it } from 'vitest';
import cs from '../fixtures/programs/curriculum-cs-ms.json';
import type { ProgramSummary } from '../api/programs';
import {
  checkPlanLink,
  hasPlanLink,
  matchProgramRef,
  readPlanLink,
} from './programLinks';
import type { PlanLink } from './programLinks';

const STANDARD = 'cs-ms-boston-2026-2027-standard';
const BRIDGE = 'cs-ms-boston-2026-2027-bridge';
const revisions: Record<string, string> = cs.proposed_plan_revisions;
const body = { ...cs.body, plan_revisions: revisions };
const standardPlan = cs.body.plans.find((p) => p.plan_id === STANDARD)!;
const link: PlanLink = {
  program_id: 'cs-ms',
  plan_id: STANDARD,
  campus: 'boston',
  catalog_year: '2026-2027',
  pathway: 'standard',
  concentration: null,
  plan_content_sha256: revisions[STANDARD]!,
};
// The eight keys as the share box writes them (models/programFormat.ts shareUrl); null leaves a key out.
function query(over: Record<string, string | null> = {}) {
  const fields: Record<string, string | null> = {
    plan_v: '1',
    program: 'cs-ms',
    plan: STANDARD,
    campus: 'boston',
    catalog_year: '2026-2027',
    pathway: 'standard',
    concentration: 'null',
    plan_revision: link.plan_content_sha256,
    ...over,
  };
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(fields))
    if (value !== null) params.append(key, value);
  return params;
}
const plus = (key: string, value: string) => {
  const params = query();
  params.append(key, value);
  return params;
};

describe('reading a plan link (read_plan_link)', () => {
  it('reads the eight keys as the share box writes them', () => {
    expect(readPlanLink(query())).toEqual(link);
  });
  it('reads a concentration given as a JSON string', () => {
    expect(
      readPlanLink(query({ concentration: '"AI 方向"' }))?.concentration,
    ).toBe('AI 方向');
    expect(
      readPlanLink(query({ concentration: '"null"' }))?.concentration,
    ).toBe('null');
  });
  it.each([
    ['a key left out', query({ plan_revision: null })],
    ['a key written twice', plus('plan', STANDARD)],
    ['a course with it, even a blank one', plus('course', '')],
    ['another format version', query({ plan_v: '2' })],
    ['a program ID with capitals', query({ program: 'CS-MS' })],
    ['a plan ID that starts with a hyphen', query({ plan: '-standard' })],
    ['a campus that starts with a digit', query({ campus: '1boston' })],
    [
      'a catalog year that is not two years running',
      query({ catalog_year: '2026-2028' }),
    ],
    ['a pathway there is none of', query({ pathway: 'online' })],
    ['a concentration that is not JSON', query({ concentration: 'AI' })],
    [
      'a concentration that is not one JSON value',
      query({ concentration: '"a" "b"' }),
    ],
    ['a lone quote for a concentration', query({ concentration: '"' })],
    ['a blank concentration', query({ concentration: '"   "' })],
    [
      'a concentration of 101 characters',
      query({ concentration: JSON.stringify('x'.repeat(101)) }),
    ],
    [
      'a content version in capitals',
      query({ plan_revision: link.plan_content_sha256.toUpperCase() }),
    ],
    // Streamlit's 2048 characters for all eight together cannot be reached by values that keep to their patterns
    // (under 1,500 at most), so the pattern refuses an overlong link first.
    ['a program ID of 65 characters', query({ program: 'c'.repeat(65) })],
    ['a plan ID of 101 characters', query({ plan: 'p'.repeat(101) })],
    ['a campus of 41 characters', query({ campus: 'b'.repeat(41) })],
  ])('refuses a link with %s', (_name, params) => {
    expect(readPlanLink(params)).toBeNull();
  });
  it('takes a program ID, a plan ID and a campus at their longest', () => {
    expect(
      readPlanLink(
        query({
          program: 'c'.repeat(64),
          plan: 'p'.repeat(100),
          campus: 'b'.repeat(40),
        }),
      ),
    ).toMatchObject({
      program_id: 'c'.repeat(64),
      plan_id: 'p'.repeat(100),
      campus: 'b'.repeat(40),
    });
  });
  it('takes a concentration of 100 characters, counted as characters', () => {
    const hundred = '😀'.repeat(100);
    expect(
      readPlanLink(query({ concentration: JSON.stringify(hundred) }))
        ?.concentration,
    ).toBe(hundred);
  });
  it('is a plan link with any of its keys but program; program alone is not', () => {
    expect(hasPlanLink(new URLSearchParams('program=cs-ms'))).toBe(false);
    expect(hasPlanLink(new URLSearchParams('course=CS-5800'))).toBe(false);
    for (const key of [
      'plan_v',
      'plan',
      'campus',
      'catalog_year',
      'pathway',
      'concentration',
      'plan_revision',
    ])
      expect(hasPlanLink(new URLSearchParams(`${key}=`))).toBe(true);
  });
});

describe('checking a plan link against the program read now (resolve_plan_link)', () => {
  it('chooses the exact plan at the same version, checked against its sources', () => {
    expect(checkPlanLink(body, link)).toBe('ready');
  });
  it('the plan at another content version, or in another scope, is stale', () => {
    expect(
      checkPlanLink(body, { ...link, plan_content_sha256: 'f'.repeat(64) }),
    ).toBe('stale');
    expect(checkPlanLink(body, { ...link, concentration: 'AI' })).toBe('stale');
  });
  it('a plan the program no longer has is missing', () => {
    expect(checkPlanLink(body, { ...link, plan_id: 'cs-ms-gone' })).toBe(
      'missing',
    );
  });
  it('a plan not checked against its sources is a draft', () => {
    expect(
      checkPlanLink(body, {
        ...link,
        plan_id: BRIDGE,
        pathway: 'bridge',
        plan_content_sha256: revisions[BRIDGE]!,
      }),
    ).toBe('draft');
  });
  it('a draft at another content version is stale: the version is checked first, as in Streamlit', () => {
    expect(
      checkPlanLink(body, {
        ...link,
        plan_id: BRIDGE,
        pathway: 'bridge',
        plan_content_sha256: 'f'.repeat(64),
      }),
    ).toBe('stale');
  });
  it('a program without its plan table is unavailable', () => {
    expect(checkPlanLink({ ...body, plan_schema_available: false }, link)).toBe(
      'unavailable',
    );
  });
  it.each([
    ['not an answer at all', null],
    ['another program', { ...body, program_id: 'ds-ms' }],
    ['plans that are not a list', { ...body, plans: {} }],
    [
      'more than 100 plans',
      {
        ...body,
        // Each its own ID and scope, so only the count is wrong.
        plans: Array.from({ length: 101 }, (_, i) => ({
          ...standardPlan,
          plan_id: `cs-ms-p${i}`,
          concentration: `Synthetic ${i}`,
        })),
      },
    ],
    [
      'a document that is not a plan',
      { ...body, plans: [...body.plans, { plan_id: 'x' }] },
    ],
    [
      "another program's plan",
      {
        ...body,
        plans: [...body.plans, { ...standardPlan, program_id: 'ds-ms' }],
      },
    ],
    [
      'an ID twice, in another scope',
      {
        ...body,
        plans: [...body.plans, { ...standardPlan, concentration: 'AI' }],
      },
    ],
    [
      'a scope twice',
      {
        ...body,
        plans: [...body.plans, { ...standardPlan, plan_id: 'cs-ms-copy' }],
      },
    ],
    ['no content version for the plan', { ...body, plan_revisions: {} }],
  ])('%s cannot be trusted: unusable', (_name, answer) => {
    expect(checkPlanLink(answer, link)).toBe('unusable');
  });
});

describe('matching a /?program= ref (match_program_ref)', () => {
  const rows: ProgramSummary[] = [
    ['cs-ms', 'CS'],
    ['ds-ms', 'DS'],
    ['x-ms', 'X'],
    ['y-ms', 'X'],
    ['other', 'cs-ms'],
  ].map(([program_id, prefix]) => ({
    program_id: program_id!,
    prefix: prefix!,
    full_name: 'Synthetic',
    course_count: 1,
    plan_count: 0,
  }));
  it.each([
    ['cs-ms', 'cs-ms'],
    ['CS-MS', 'cs-ms'],
    ['cs', 'cs-ms'],
    [' Ds ', 'ds-ms'],
  ])('%j names %s, by its ID or its prefix in any case', (ref, id) => {
    expect(matchProgramRef(ref, rows)).toBe(id);
  });
  it('an ID wins over a prefix that is spelled the same', () => {
    expect(matchProgramRef('cs-ms', rows)).toBe('cs-ms');
  });
  it.each(['', '   ', 'nope', 'x'])(
    '%j names no program (a prefix two share names neither)',
    (ref) => {
      expect(matchProgramRef(ref, rows)).toBeNull();
    },
  );
});
