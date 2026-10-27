import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { expect, it } from 'vitest';
import { curriculumQuery } from '../api/programs';
import { createQueryClient } from '../api/queries';
import curriculum from '../fixtures/programs/curriculum-cs-ms.json';
import { plansSignature } from '../models/chatPlans';
import { WithApi } from '../test/withApi';
import { ProgramsProvider, useProgramsState } from './ProgramsContext';

const CS = 'cs-ms';
const DS = 'ds-ms';
const ALIGN = 'cs-ms-boston-2026-2027-align';
const STANDARD = 'cs-ms-boston-2026-2027-standard';
const revisions: Record<string, string> = curriculum.proposed_plan_revisions;
const body = (
  planRevisions: Record<string, string> = revisions,
  plans: readonly unknown[] = curriculum.body.plans,
) => ({ ...curriculum.body, plans, plan_revisions: planRevisions });
const revised = () => body({ ...revisions, [ALIGN]: 'f'.repeat(64) });
// The cache tells its readers in a batch, a moment later.
const moment = () =>
  act(() => new Promise<void>((resolve) => setTimeout(resolve, 20)));

// The provider over a cache that already has cs-ms's answer; `owner` is read on every render, so a rerender changes it.
// known: false starts before /auth/me has said who is looking.
function setup(known = true) {
  const client = createQueryClient();
  client.setQueryData(curriculumQuery(CS).queryKey, body());
  const props: { owner: string | undefined } = {
    owner: known ? 'member:u-1' : undefined,
  };
  const view = renderHook(() => useProgramsState(), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <WithApi client={client}>
        <ProgramsProvider owner={props.owner}>{children}</ProgramsProvider>
      </WithApi>
    ),
  });
  const answer = (value: unknown) =>
    act(() => {
      client.setQueryData(curriculumQuery(CS).queryKey, value);
    });
  return { client, props, answer, ...view };
}

it('keeps one choice per program', () => {
  const { result } = setup();
  act(() => result.current.choosePlan(CS, STANDARD, plansSignature(body())));
  act(() => result.current.choosePlan(DS, 'ds-ms-plan', '[]'));
  expect(result.current.chosenPlan(CS)).toBe(STANDARD);
  expect(result.current.chosenPlan(DS)).toBe('ds-ms-plan');
  act(() => result.current.choosePlan(CS, null, plansSignature(body())));
  expect(result.current.chosenPlan(CS)).toBeNull();
  expect(result.current.chosenPlan(DS)).toBe('ds-ms-plan');
});

it('a plan list that changed under the choice takes it and says so, and a list that changes back does not bring it back', async () => {
  const { result, answer } = setup();
  act(() => result.current.choosePlan(CS, STANDARD, plansSignature(body())));
  answer(revised());
  await waitFor(() => expect(result.current.chosenPlan(CS)).toBeNull());
  expect(result.current.planRevised(CS)).toBe(true);
  answer(body());
  await moment();
  expect(result.current.chosenPlan(CS)).toBeNull();
  act(() => result.current.choosePlan(CS, ALIGN, plansSignature(body())));
  expect(result.current.chosenPlan(CS)).toBe(ALIGN);
  expect(result.current.planRevised(CS)).toBe(false);
});

it('a plan no longer offered goes without a word', async () => {
  const { result, answer } = setup();
  act(() => result.current.choosePlan(CS, STANDARD, plansSignature(body())));
  // The same versions, but the plan's document no longer reads as a plan: availablePlans drops it.
  answer(
    body(
      revisions,
      curriculum.body.plans.map((plan) =>
        plan.plan_id === STANDARD ? { ...plan, coverage: 'whole' } : plan,
      ),
    ),
  );
  await waitFor(() => expect(result.current.chosenPlan(CS)).toBeNull());
  expect(result.current.planRevised(CS)).toBe(false);
});

it('a choice under the list as it is stays', async () => {
  const { result, answer } = setup();
  act(() => result.current.choosePlan(CS, STANDARD, plansSignature(body())));
  answer(body());
  await moment();
  expect(result.current.chosenPlan(CS)).toBe(STANDARD);
  expect(result.current.planRevised(CS)).toBe(false);
});

it('forget takes the choice and the notice', async () => {
  const { result, answer } = setup();
  act(() => result.current.choosePlan(CS, STANDARD, plansSignature(body())));
  answer(revised());
  await waitFor(() => expect(result.current.planRevised(CS)).toBe(true));
  act(() => result.current.forget(CS));
  expect(result.current.planRevised(CS)).toBe(false);
  act(() => result.current.choosePlan(CS, STANDARD, plansSignature(revised())));
  expect(result.current.chosenPlan(CS)).toBe(STANDARD);
  act(() => result.current.forget(CS));
  expect(result.current.chosenPlan(CS)).toBeNull();
});

it('another person, or nobody, looking empties it; the first answer of /auth/me does not', () => {
  const { result, props, rerender } = setup(false);
  act(() => result.current.choosePlan(CS, STANDARD, plansSignature(body())));
  props.owner = 'member:u-1';
  rerender();
  expect(result.current.chosenPlan(CS)).toBe(STANDARD);
  props.owner = 'guest';
  rerender();
  expect(result.current.chosenPlan(CS)).toBeNull();
});
