import { expect, it } from 'vitest';
import curriculum from '../fixtures/programs/curriculum-cs-ms.json';
import {
  chatPlans,
  planRevisions,
  planSelection,
  plansSignature,
} from './chatPlans';

// The answer as #36's API gives it: plan_revisions at the top level.
const body = {
  ...curriculum.body,
  plan_revisions: curriculum.proposed_plan_revisions,
};
const revisions = curriculum.proposed_plan_revisions;

it('offers the source-checked plans with their content versions, as Streamlit does, never a draft', () => {
  expect(
    chatPlans(body, 'cs-ms').map(({ plan, revision }) => [
      plan.plan_id,
      revision,
    ]),
  ).toEqual([
    ['cs-ms-boston-2026-2027-align', revisions['cs-ms-boston-2026-2027-align']],
    [
      'cs-ms-boston-2026-2027-standard',
      revisions['cs-ms-boston-2026-2027-standard'],
    ],
    [
      'cs-ms-boston-2025-2026-standard',
      revisions['cs-ms-boston-2025-2026-standard'],
    ],
  ]);
});

it('a plan without a content version, or with one that is not a SHA-256, cannot be chosen', () => {
  const ids = (value: unknown) =>
    chatPlans(value, 'cs-ms').map(({ plan }) => plan.plan_id);
  expect(ids(curriculum.body)).toEqual([]);
  expect(
    ids({
      ...body,
      plan_revisions: {
        ...revisions,
        'cs-ms-boston-2026-2027-align': 'not-a-digest',
        'cs-ms-boston-2025-2026-standard':
          revisions['cs-ms-boston-2025-2026-standard'].toUpperCase(),
      },
    }),
  ).toEqual(['cs-ms-boston-2026-2027-standard']);
  expect(planRevisions({ plan_revisions: ['x'] })).toEqual({});
  expect(planRevisions(null)).toEqual({});
});

it('offers nothing for another program, without the plan table, or for a broken answer', () => {
  expect(chatPlans(body, 'ds-ms')).toEqual([]);
  expect(chatPlans({ ...body, plan_schema_available: false }, 'cs-ms')).toEqual(
    [],
  );
  expect(chatPlans({ ...body, semesters: 'x' }, 'cs-ms')).toEqual([]);
  expect(chatPlans(undefined, 'cs-ms')).toEqual([]);
});

const plan = (planId: string) =>
  curriculum.body.plans.find(({ plan_id }) => plan_id === planId)!;
const offered = (plans: unknown[], more: Record<string, string> = {}) =>
  chatPlans(
    { ...body, plans, plan_revisions: { ...revisions, ...more } },
    'cs-ms',
  ).map(({ plan }) => plan.plan_id);

it('offers a list of 100 plans, and nothing from a list of 101', () => {
  // Each its own ID and scope, so only the length can turn them away.
  const list = (length: number) =>
    Array.from({ length }, (_, i) => ({
      ...plan('cs-ms-boston-2026-2027-standard'),
      plan_id: `plan-${i}`,
      concentration: `Concentration ${i}`,
    }));
  const versions = (length: number) =>
    Object.fromEntries(
      list(length).map(({ plan_id }) => [plan_id, 'a'.repeat(64)]),
    );
  expect(offered(list(100), versions(100))).toHaveLength(100);
  expect(offered(list(101), versions(101))).toEqual([]);
});

it('offers no plan whose ID or scope another plan shares, nor another program’s, as the program page lists them', () => {
  const align = plan('cs-ms-boston-2026-2027-align');
  const older = plan('cs-ms-boston-2025-2026-standard');
  const all = curriculum.body.plans;
  expect(
    offered([...all, { ...align, plan_id: 'align-again' }], {
      'align-again': 'b'.repeat(64),
    }),
  ).toEqual([
    'cs-ms-boston-2026-2027-standard',
    'cs-ms-boston-2025-2026-standard',
  ]);
  expect(offered([...all, { ...older, concentration: 'Systems' }])).toEqual([
    'cs-ms-boston-2026-2027-align',
    'cs-ms-boston-2026-2027-standard',
  ]);
  expect(
    offered([...all, { ...align, plan_id: 'ds-plan', program_id: 'ds-ms' }], {
      'ds-plan': 'c'.repeat(64),
    }),
  ).toEqual(offered(all));
});

it('as Streamlit: a list with one document that is not a plan offers none, and another program’s IDs count too', () => {
  const align = plan('cs-ms-boston-2026-2027-align');
  const all = curriculum.body.plans;
  expect(offered(all)).toHaveLength(3);
  expect(
    offered([...all, { ...align, plan_id: 'broken', catalog_year: '26-27' }]),
  ).toEqual([]);
  // The same plan ID under another program: neither is offered.
  expect(offered([...all, { ...align, program_id: 'ds-ms' }])).toEqual([
    'cs-ms-boston-2026-2027-standard',
    'cs-ms-boston-2025-2026-standard',
  ]);
});

it('a question carries the plan’s scope and the version the page showed', () => {
  const [align] = chatPlans(body, 'cs-ms');
  expect(planSelection(align!)).toEqual({
    program_id: 'cs-ms',
    plan_id: 'cs-ms-boston-2026-2027-align',
    campus: align!.plan.campus,
    catalog_year: '2026-2027',
    pathway: 'align',
    concentration: null,
    plan_content_sha256: revisions['cs-ms-boston-2026-2027-align'],
  });
});

it('a question carries the plan’s concentration, and the version from plan_revisions, not the source page’s digest', () => {
  const standard = plan('cs-ms-boston-2026-2027-standard');
  const [chosen] = chatPlans(
    {
      ...body,
      plans: [{ ...standard, concentration: 'Artificial Intelligence' }],
    },
    'cs-ms',
  );
  expect(standard.source_html_sha256).toMatch(/^[0-9a-f]{64}$/);
  expect(planSelection(chosen!)).toMatchObject({
    concentration: 'Artificial Intelligence',
    plan_content_sha256: revisions['cs-ms-boston-2026-2027-standard'],
  });
});

it('the list’s signature follows every plan’s version, drafts included, and not their order', () => {
  const reordered = Object.fromEntries(Object.entries(revisions).reverse());
  expect(plansSignature({ plan_revisions: reordered })).toBe(
    plansSignature(body),
  );
  expect(
    plansSignature({
      plan_revisions: {
        ...revisions,
        'cs-ms-boston-2026-2027-bridge': 'f'.repeat(64),
      },
    }),
  ).not.toBe(plansSignature(body));
  expect(plansSignature({ plan_revisions: {} })).not.toBe(plansSignature(body));
});
