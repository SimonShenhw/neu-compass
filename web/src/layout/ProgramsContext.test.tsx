import { QueryObserver } from '@tanstack/react-query';
import type { QueryClient } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { expect, it } from 'vitest';
import type { DraftRequest } from '../api/draft';
import { curriculumQuery } from '../api/programs';
import { createQueryClient } from '../api/queries';
import stale from '../fixtures/draft/draft-409-stale.json';
import curriculum from '../fixtures/programs/curriculum-cs-ms.json';
import { plansSignature } from '../models/chatPlans';
import { draftAnswer } from '../pages/searchRouteTestUtils';
import { fakeApi, held, json } from '../test/fakeApi';
import { WithApi } from '../test/withApi';
import { ProgramsProvider, useProgramsState } from './ProgramsContext';
import type { DraftPlan } from './ProgramsContext';

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

// The draft. The checks are answered from R4b's exported answers (draftAnswer) unless a test holds one back.
const shownUnder = (over: Partial<DraftPlan> = {}): DraftPlan => ({
  programId: CS,
  planId: STANDARD,
  revision: revisions[STANDARD]!,
  signature: plansSignature(body()),
  ...over,
});
const nothing = { answer: null, checking: false, failure: null };
// The program page reads cs-ms while it is open. Without a reader TanStack stops a read on its way once the provider
// lets go of the refused choice, and the refusal would be settled by that alone.
const pageReading = (client: QueryClient) =>
  new QueryObserver(client, {
    ...curriculumQuery(CS),
    enabled: false,
  }).subscribe(() => {});
const sentIds = (calls: readonly { body: unknown }[]) =>
  calls.map((call) => (call.body as DraftRequest).course_ids);

it('the draft keeps its courses across programs and plans, checked once under each plan shown', async () => {
  const api = fakeApi((call) =>
    json(draftAnswer(STANDARD, call.body as DraftRequest)),
  );
  const { result } = setup();
  act(() => result.current.showDraft(shownUnder()));
  await waitFor(() =>
    expect(result.current.draftView(shownUnder()).answer).not.toBeNull(),
  );
  act(() => result.current.addToDraft(shownUnder(), 'CS 5010'));
  await waitFor(() =>
    expect(result.current.draftView(shownUnder()).checking).toBe(false),
  );
  // Shown again under the plan of the last check: not checked again.
  act(() => result.current.showDraft(shownUnder()));
  const elsewhere = shownUnder({
    programId: DS,
    planId: 'ds-ms-plan',
    revision: 'd'.repeat(64),
  });
  act(() => result.current.showDraft(elsewhere));
  expect(api.calls.map((call) => call.path)).toEqual([
    `/programs/${CS}/plans/${STANDARD}/draft`,
    `/programs/${CS}/plans/${STANDARD}/draft`,
    `/programs/${DS}/plans/ds-ms-plan/draft`,
  ]);
  expect(sentIds(api.calls)).toEqual([[], [], ['c-cs-5010']]);
  // What was shown under cs-ms is not this plan's.
  expect(result.current.draftView(elsewhere)).toEqual({
    ...nothing,
    checking: true,
  });
  expect(result.current.draftView(shownUnder())).toEqual(nothing);
});

it('a check on its way when someone else is looking counts for nothing, and their draft starts empty', async () => {
  let later: ReturnType<typeof held> | null = null;
  const api = fakeApi(
    (call) =>
      later?.response ?? json(draftAnswer(STANDARD, call.body as DraftRequest)),
  );
  const { result, props, rerender } = setup();
  act(() => result.current.choosePlan(CS, STANDARD, plansSignature(body())));
  act(() => result.current.showDraft(shownUnder()));
  act(() => result.current.addToDraft(shownUnder(), 'CS 5010'));
  await waitFor(() =>
    expect(result.current.draftView(shownUnder()).checking).toBe(false),
  );
  later = held();
  act(() => result.current.removeFromDraft(shownUnder(), 'c-none'));
  props.owner = 'guest';
  rerender();
  later.answer(
    json(
      draftAnswer(STANDARD, {
        plan_content_sha256: revisions[STANDARD]!,
        course_ids: ['c-cs-5010'],
      }),
    ),
  );
  await moment();
  expect(result.current.draftView(shownUnder())).toEqual(nothing);
  later = null;
  act(() => result.current.showDraft(shownUnder()));
  expect(sentIds(api.calls).at(-1)).toEqual([]);
});

it('forget drops a check on its way under the program’s plan, and shown again the draft is checked again', async () => {
  const later = held();
  let first = true;
  const api = fakeApi((call) => {
    if (!first) return json(draftAnswer(STANDARD, call.body as DraftRequest));
    first = false;
    return later.response;
  });
  const { result } = setup();
  act(() => result.current.showDraft(shownUnder()));
  act(() => result.current.forget(CS));
  later.answer(
    json(
      draftAnswer(STANDARD, {
        plan_content_sha256: revisions[STANDARD]!,
        course_ids: [],
      }),
    ),
  );
  await moment();
  expect(result.current.draftView(shownUnder())).toEqual(nothing);
  act(() => result.current.showDraft(shownUnder()));
  expect(api.calls).toHaveLength(2);
});

it('an earlier check that fails after a later one was answered says nothing', async () => {
  const first = held();
  let calls = 0;
  fakeApi((call) =>
    ++calls === 1
      ? first.response
      : json(draftAnswer(STANDARD, call.body as DraftRequest)),
  );
  const { result } = setup();
  act(() => result.current.showDraft(shownUnder()));
  act(() => result.current.addToDraft(shownUnder(), 'CS 5010'));
  await waitFor(() =>
    expect(result.current.draftView(shownUnder()).checking).toBe(false),
  );
  first.answer(json({ error_type: 'server_error' }, 503));
  await moment();
  expect(result.current.draftView(shownUnder()).failure).toBeNull();
  expect(result.current.draftView(shownUnder()).answer).not.toBeNull();
});

it('an answer for another content version does not become the draft', async () => {
  const api = fakeApi((call) => {
    const request = call.body as DraftRequest;
    const answer = draftAnswer(STANDARD, request);
    return json(
      api.calls.length === 1
        ? { ...answer, plan_content_sha256: 'e'.repeat(64) }
        : answer,
    );
  });
  const { result } = setup();
  act(() => result.current.addToDraft(shownUnder(), 'CS 5010'));
  await waitFor(() =>
    expect(result.current.draftView(shownUnder()).checking).toBe(false),
  );
  act(() => result.current.retryDraft(shownUnder()));
  expect(sentIds(api.calls)).toEqual([[], []]);
});

it('plans that cannot be read again after a refused plan leave R4b’s sentence', async () => {
  fakeApi((call) =>
    call.method === 'POST'
      ? json(stale.body, 409)
      : json({ error_type: 'server_error' }, 503),
  );
  const { client, result } = setup();
  pageReading(client);
  act(() => result.current.choosePlan(CS, STANDARD, plansSignature(body())));
  act(() => result.current.showDraft(shownUnder()));
  await waitFor(() => expect(result.current.planRefused(CS)).toBe(true));
  expect(result.current.chosenPlan(CS)).toBeNull();
  expect(result.current.planRevised(CS)).toBe(false);
});

it('a refused plan chosen again before the plans are read again leaves nothing to say', async () => {
  const read = held();
  fakeApi((call) =>
    call.method === 'POST' ? json(stale.body, 409) : read.response,
  );
  const { client, result } = setup();
  pageReading(client);
  act(() => result.current.choosePlan(CS, STANDARD, plansSignature(body())));
  act(() => result.current.showDraft(shownUnder()));
  await waitFor(() => expect(result.current.chosenPlan(CS)).toBeNull());
  act(() => result.current.choosePlan(CS, STANDARD, plansSignature(body())));
  // Plans that did not change would have said R4b's sentence; the read is in before anything is looked at.
  read.answer(json(body()));
  await waitFor(() => expect(client.isFetching()).toBe(0));
  await moment();
  expect(result.current.planRefused(CS)).toBe(false);
  expect(result.current.planRevised(CS)).toBe(false);
  expect(result.current.chosenPlan(CS)).toBe(STANDARD);
});
