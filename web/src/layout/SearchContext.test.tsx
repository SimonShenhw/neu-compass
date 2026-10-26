import { act, renderHook, waitFor } from '@testing-library/react';
import type { QueryClient } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { expect, it } from 'vitest';
import { curriculumQuery } from '../api/programs';
import { configQuery, createQueryClient } from '../api/queries';
import ds from '../fixtures/landing/curriculum-ds-ms.json';
import curriculum from '../fixtures/programs/curriculum-cs-ms.json';
import alias from '../fixtures/search/alias-cs-6140.json';
import { fakeApi, json } from '../test/fakeApi';
import type { Call } from '../test/fakeApi';
import { WithApi, seededQueryClient } from '../test/withApi';
import { SearchProvider, useSearch } from './SearchContext';

const CS = 'cs-ms';
// A program with no plans (R3d's landing fixture).
const DS = 'ds-ms';
const ALIGN = 'cs-ms-boston-2026-2027-align';
const STANDARD = 'cs-ms-boston-2026-2027-standard';
const revisions = curriculum.proposed_plan_revisions;
const programBody = (planRevisions: Record<string, string> = revisions) => ({
  ...curriculum.body,
  plan_revisions: planRevisions,
});
const stream = (lines: readonly unknown[]) =>
  new Response(lines.map((line) => JSON.stringify(line)).join('\n') + '\n');
const refusal = (reason: string) =>
  json(
    {
      detail: '固定的中文说明',
      error_type: 'conflict',
      status_code: 409,
      reason,
    },
    409,
  );

// The provider under a query client of the test's own; `owner` is read on every render, so a rerender changes it.
function setup({
  feedback = true,
  // true: /auth/me has not said yet who is looking.
  unknown = false,
  answer = () => stream(alias.lines),
  program = () => json(programBody()),
}: {
  feedback?: boolean;
  unknown?: boolean;
  answer?: (call: Call) => Response | Promise<Response>;
  program?: (call: Call) => Response;
} = {}) {
  const api = fakeApi(async (call) =>
    call.path === '/chat'
      ? answer(call)
      : call.path === `/programs/${CS}`
        ? program(call)
        : call.path === `/programs/${DS}`
          ? json(ds.body)
          : json({}, 404),
  );
  const client: QueryClient = seededQueryClient({
    config: { answer_feedback_enabled: feedback, login_available: true },
  });
  const props: { owner: string | undefined } = {
    owner: unknown ? undefined : 'guest',
  };
  const hook = renderHook(() => useSearch(), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <WithApi client={client}>
        <SearchProvider owner={props.owner}>{children}</SearchProvider>
      </WithApi>
    ),
  });
  const chats = () =>
    api.calls.filter((call) => call.path === '/chat').map((call) => call.body);
  return { api, client, props, hook, chats };
}
async function choose(hook: ReturnType<typeof setup>['hook'], planId: string) {
  act(() => hook.result.current.chooseProgram(CS));
  await waitFor(() => expect(hook.result.current.plans).toHaveLength(3));
  act(() => hook.result.current.choosePlan(planId));
  expect(hook.result.current.plan?.plan.plan_id).toBe(planId);
}
async function asked(hook: ReturnType<typeof setup>['hook'], question: string) {
  act(() => hook.result.current.ask(question));
  await waitFor(() => expect(hook.result.current.busy).toBe(false));
}

it('a question carries what Streamlit sends: the window of history, the last answer’s courses, the program and the exact plan', async () => {
  const { hook, chats } = setup();
  await asked(hook, 'CS 6140 讲什么？');
  expect(chats()).toEqual([
    {
      query: 'CS 6140 讲什么？',
      k: 10,
      allow_feedback_capture: false,
      history: [],
      context_course_ids: [],
    },
  ]);
  await choose(hook, ALIGN);
  act(() => hook.result.current.setAllowSave(true));
  await asked(hook, '  作业量大吗？  ');
  const answer = alias.lines
    .filter((line) => line.type === 'token')
    .map((line) => line.text)
    .join('');
  expect(chats()[1]).toEqual({
    query: '作业量大吗？',
    k: 10,
    allow_feedback_capture: true,
    history: [
      { role: 'user', content: 'CS 6140 讲什么？' },
      { role: 'assistant', content: answer },
    ],
    context_course_ids: ['c-cs-6140'],
    program_id: CS,
    plan: {
      program_id: CS,
      plan_id: ALIGN,
      campus: 'boston',
      catalog_year: '2026-2027',
      pathway: 'align',
      concentration: null,
      plan_content_sha256: revisions[ALIGN],
    },
  });
  // The opt-in stays ticked: the answers after it are saved until it is unticked (the API's notice).
  expect(hook.result.current.allowSave).toBe(true);
});

it('saves nothing while answer feedback is off, even if the opt-in were ticked', async () => {
  const { hook, chats } = setup({ feedback: false });
  act(() => hook.result.current.setAllowSave(true));
  await waitFor(() => expect(hook.result.current.allowSave).toBe(false));
  await asked(hook, 'CS 5800');
  expect(chats()[0]).toMatchObject({ allow_feedback_capture: false });
  expect(hook.result.current.feedback).toBe(false);
});

it('the opt-in goes while answer feedback is off, and stays unticked when it is back on', async () => {
  const { client, hook } = setup();
  act(() => hook.result.current.setAllowSave(true));
  expect(hook.result.current.allowSave).toBe(true);
  // The query cache tells its observers a moment later.
  const feedback = async (on: boolean) => {
    act(() =>
      client.setQueryData(configQuery.queryKey, {
        answer_feedback_enabled: on,
        login_available: true,
      }),
    );
    await waitFor(() => expect(hook.result.current.feedback).toBe(on));
  };
  await feedback(false);
  expect(hook.result.current.allowSave).toBe(false);
  await feedback(true);
  expect(hook.result.current.allowSave).toBe(false);
});

it('says nothing of answer feedback until /config has answered', () => {
  fakeApi(() => json({}, 404));
  const client = createQueryClient();
  const hook = renderHook(() => useSearch(), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <WithApi client={client}>
        <SearchProvider owner="guest">{children}</SearchProvider>
      </WithApi>
    ),
  });
  expect(hook.result.current.feedback).toBeNull();
});

it('sends no blank question and none over 500 characters', async () => {
  const { hook, chats } = setup();
  act(() => hook.result.current.ask('   '));
  act(() => hook.result.current.ask('字'.repeat(501)));
  expect(hook.result.current.turns).toEqual([]);
  await asked(hook, '𝟙'.repeat(500));
  expect(chats()).toHaveLength(1);
});

it.each([
  'plan_missing',
  'plan_stale',
  'plan_draft',
  'plan_unusable',
  'plan_unavailable',
])(
  'a %s refusal clears the plan, keeps the program and asks for its plans again',
  async (reason) => {
    const { api, hook } = setup({ answer: () => refusal(reason) });
    await choose(hook, STANDARD);
    await asked(hook, 'CS 5800');
    expect(hook.result.current.turns[0]).toMatchObject({
      status: 'failed',
      failure: { status: 409, reason },
    });
    expect(hook.result.current.plan).toBeNull();
    expect(hook.result.current.programId).toBe(CS);
    await waitFor(() => expect(api.count('GET', `/programs/${CS}`)).toBe(2));
    expect(hook.result.current.planRevised).toBe(false);
  },
);

it.each(['program_ambiguous', 'program_conflict'])(
  'a %s refusal keeps the choices and the plans as they are',
  async (reason) => {
    const { api, hook } = setup({ answer: () => refusal(reason) });
    await choose(hook, STANDARD);
    await asked(hook, 'AAI first semester');
    expect(hook.result.current.plan?.plan.plan_id).toBe(STANDARD);
    expect(api.count('GET', `/programs/${CS}`)).toBe(1);
  },
);

it('a refusal clears only the plan it refused: one chosen since stays', async () => {
  let release: (response: Response) => void = () => {};
  const held = new Promise<Response>((resolve) => (release = resolve));
  const { hook } = setup({ answer: () => held });
  await choose(hook, STANDARD);
  act(() => hook.result.current.ask('CS 5800'));
  act(() => hook.result.current.choosePlan(ALIGN));
  release(refusal('plan_stale'));
  await waitFor(() => expect(hook.result.current.busy).toBe(false));
  expect(hook.result.current.plan?.plan.plan_id).toBe(ALIGN);
});

it('a plan list that changed under the choice takes it, once, and says so until the next choice', async () => {
  const { client, hook } = setup();
  await choose(hook, ALIGN);
  act(() =>
    client.setQueryData(
      curriculumQuery(CS).queryKey,
      programBody({ ...revisions, [STANDARD]: 'f'.repeat(64) }),
    ),
  );
  await waitFor(() => expect(hook.result.current.plan).toBeNull());
  expect(hook.result.current.planRevised).toBe(true);
  act(() => hook.result.current.choosePlan(ALIGN));
  expect(hook.result.current.plan?.plan.plan_id).toBe(ALIGN);
  expect(hook.result.current.planRevised).toBe(false);
});

it('a plan list that can no longer be read takes the choice, and says it cannot check plans', async () => {
  let gone = false;
  const { client, hook } = setup({
    program: () =>
      gone
        ? json({ detail: 'x', error_type: 'not_found', status_code: 404 }, 404)
        : json(programBody()),
  });
  await choose(hook, ALIGN);
  gone = true;
  await act(() =>
    client.invalidateQueries({ queryKey: curriculumQuery(CS).queryKey }),
  );
  await waitFor(() => expect(hook.result.current.plansUnavailable).toBe(true));
  expect(hook.result.current.plan).toBeNull();
  expect(hook.result.current.plans).toEqual([]);
  expect(hook.result.current.planRevised).toBe(false);
});

it('another program takes the plan, without saying that the plans changed', async () => {
  const { client, hook } = setup();
  await choose(hook, ALIGN);
  act(() => hook.result.current.chooseProgram(DS));
  await waitFor(() =>
    expect(client.getQueryData(curriculumQuery(DS).queryKey)).toBeDefined(),
  );
  expect(hook.result.current.programId).toBe(DS);
  expect(hook.result.current.plan).toBeNull();
  expect(hook.result.current.planRevised).toBe(false);
});

it('a new program clears the plan and the note', async () => {
  const { client, hook } = setup();
  await choose(hook, ALIGN);
  act(() =>
    client.setQueryData(
      curriculumQuery(CS).queryKey,
      programBody({ ...revisions, [STANDARD]: 'f'.repeat(64) }),
    ),
  );
  await waitFor(() => expect(hook.result.current.planRevised).toBe(true));
  act(() => hook.result.current.chooseProgram(null));
  expect(hook.result.current.programId).toBeNull();
  expect(hook.result.current.plan).toBeNull();
  expect(hook.result.current.planRevised).toBe(false);
});

it('another person, or nobody, looking empties it all; /auth/me’s first answer only says who it was all along', async () => {
  const { hook, props } = setup({ unknown: true });
  await asked(hook, 'CS 5800');
  await choose(hook, ALIGN);
  act(() => hook.result.current.setAllowSave(true));
  props.owner = 'member:u-1';
  hook.rerender();
  expect(hook.result.current.turns).toHaveLength(1);
  expect(hook.result.current.plan?.plan.plan_id).toBe(ALIGN);
  props.owner = 'guest';
  hook.rerender();
  await waitFor(() => expect(hook.result.current.turns).toEqual([]));
  expect(hook.result.current.programId).toBeNull();
  expect(hook.result.current.plan).toBeNull();
  expect(hook.result.current.allowSave).toBe(false);
});
