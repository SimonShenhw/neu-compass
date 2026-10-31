import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { axe } from 'vitest-axe';
import { privacyQuery } from '../api/privacy';
import { curriculumQuery, programListQuery } from '../api/programs';
import { configQuery, createQueryClient, meQuery } from '../api/queries';
import type { Member } from '../api/queries';
import { readyQuery } from '../api/ready';
import coop from '../fixtures/landing/coop-guest.json';
import privacy from '../fixtures/privacy/privacy-90-days-feedback-contact.json';
import alias from '../fixtures/search/alias-cs-6140.json';
import receipt from '../fixtures/search/feedback-receipt.json';
import votes from '../fixtures/search/feedback-responses.json';
import { SINGLE_FOLLOWUPS } from '../features/search-answer/SearchConversation';
import { CAPTURE_LABEL, CAPTURE_OFF, CAPTURE_REGION } from '../layout/AskBar';
import { PLAN_PLACEHOLDER } from '../models/programFormat';
import { apiError, asked, held, json } from '../test/fakeApi';
import { SEEDED_READY, seededQueryClient } from '../test/withApi';
import {
  PLAN_NOTE,
  PLAN_REVISED,
  PLANS_UNAVAILABLE,
  PROGRAM_NOTE,
  PROGRAMS_UNAVAILABLE,
} from './SearchRoute';
import {
  ALIGN,
  CS,
  STANDARD,
  answerText,
  chats,
  choose,
  combobox,
  csBody,
  page,
  programRows,
  revisions,
  stateOf,
  stream,
  where,
  world,
} from './searchRouteTestUtils';

const LANDING = [
  'GET /coop',
  'GET /privacy',
  'GET /programs',
  'GET /programs/aai-ms',
  'GET /programs/cs-ms',
  'GET /programs/ds-ms',
];
const CS_PROGRAM = 'MS in Computer Science (synthetic) · cs-ms';
const ALIGN_PLAN =
  'boston · Catalog 2026-2027 · Align · 共同部分／未限定 concentration';
const GUEST_NOTE = /^游客也能搜课、看培养方案。/;
const member: Member = {
  kind: 'member',
  userId: 'u-1',
  email: 'student@example.edu',
  displayName: null,
  contributionCount: 0,
};
// The landing has had its answers.
const landed = async () => {
  expect(
    await screen.findByRole('button', { name: '查看 CS 5010' }),
  ).toBeInTheDocument();
  expect(
    await screen.findByRole('button', { name: '去看看' }),
  ).toBeInTheDocument();
};
const ask = async (question: string) => {
  const user = userEvent.setup();
  await user.type(
    screen.getByRole('textbox', { name: '课程问题' }),
    `${question}{Enter}`,
  );
};
const answered = () => screen.findByRole('group', { name: '接着问' });
// The same question sent with the ask box's button.
const askWithButton = async (question: string) => {
  const user = userEvent.setup();
  await user.type(screen.getByRole('textbox', { name: '课程问题' }), question);
  await user.click(screen.getByRole('button', { name: '发送问题' }));
};

it('the landing asks the program list, the featured programs it has, Co-op and the privacy words, once each', async () => {
  const api = world();
  page('/');
  await landed();
  expect(api.calls.map(asked).sort()).toEqual(LANDING);
  // Listed but not featured: shown, not asked.
  expect(
    screen.getByRole('button', { name: 'PJM · 1 门课' }),
  ).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '查看 AAI 6600' })).toBeVisible();
});

it('查看 opens the course’s page with its ID, so the page does not look the code up', async () => {
  const api = world();
  page('/');
  await landed();
  await userEvent.click(screen.getByRole('button', { name: '查看 CS 5010' }));
  expect(where()).toBe('/course/CS-5010');
  expect(stateOf()).toEqual({ courseId: 'c-cs-5010' });
  expect(
    await screen.findByRole('heading', { name: 'Programming Design Paradigm' }),
  ).toBeInTheDocument();
  expect(api.count('GET', '/resolve/course')).toBe(0);
  expect(api.count('GET', '/course/c-cs-5010')).toBe(1);
});

it('a program opens its page, and Co-op its own', async () => {
  world();
  page('/');
  await landed();
  await userEvent.click(screen.getByRole('button', { name: 'CS · 6 门课' }));
  expect(where()).toBe('/programs/cs-ms');
  await userEvent.click(screen.getByRole('button', { name: 'back' }));
  await userEvent.click(await screen.findByRole('button', { name: '去看看' }));
  expect(where()).toBe('/coop');
});

it('a program’s ID goes into its page’s address encoded', async () => {
  world((call) =>
    call.path === '/programs'
      ? json([
          ...programRows,
          {
            program_id: 'x&y z',
            full_name: 'Synthetic X',
            prefix: 'XY',
            course_count: 1,
            plan_count: 0,
          },
        ])
      : undefined,
  );
  page('/');
  await landed();
  await userEvent.click(screen.getByRole('button', { name: 'XY · 1 门课' }));
  expect(where()).toBe('/programs/x%26y%20z');
});

it('the landing’s retry asks again only what failed: here a featured program and Co-op', async () => {
  let down = true;
  const api = world((call) =>
    down && (call.path === '/programs/cs-ms' || call.path === '/coop')
      ? apiError(503, 'service_unavailable', 'down')
      : undefined,
  );
  page('/');
  expect(
    await screen.findByText('部分内容暂时没加载出来。'),
  ).toBeInTheDocument();
  expect(
    screen.getByRole('button', { name: '查看 AAI 6600' }),
  ).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: '查看 CS 5010' })).toBeNull();
  down = false;
  await userEvent.click(screen.getByRole('button', { name: '重新加载' }));
  await landed();
  expect(api.count('GET', '/programs/cs-ms')).toBe(2);
  expect(api.count('GET', '/coop')).toBe(2);
  expect(api.count('GET', '/programs/aai-ms')).toBe(1);
  expect(api.count('GET', '/programs')).toBe(1);
});

it('a sample question is asked as Streamlit asks one, and focus goes to the conversation; the landing asks nothing more', async () => {
  const api = world();
  page('/');
  await landed();
  const focus = vi.spyOn(HTMLElement.prototype, 'focus');
  await userEvent.click(screen.getByRole('button', { name: 'CS 5800' }));
  const conversation = screen.getByRole('group', { name: '对话' });
  await waitFor(() => expect(conversation).toHaveFocus());
  // Without scrolling: the page stays where the student was reading.
  const call = focus.mock.contexts.indexOf(conversation);
  expect(focus.mock.calls[call]).toEqual([{ preventScroll: true }]);
  await answered();
  expect(chats(api.calls)).toEqual([
    {
      query: 'CS 5800',
      k: 10,
      allow_feedback_capture: false,
      history: [],
      context_course_ids: [],
    },
  ]);
  expect(
    screen.queryByRole('region', { name: '搜索落地内容' }),
  ).not.toBeInTheDocument();
  expect(api.calls.map(asked).sort()).toEqual(
    [...LANDING, 'POST /chat'].sort(),
  );
});

it('a follow-up carries the conversation so far and the last answer’s courses', async () => {
  const api = world();
  page('/');
  await ask('CS 6140 讲什么？');
  const followUps = await answered();
  await userEvent.click(
    within(followUps).getByRole('button', { name: SINGLE_FOLLOWUPS[1]! }),
  );
  await waitFor(() => expect(chats(api.calls)).toHaveLength(2));
  expect(chats(api.calls)[1]).toEqual({
    query: SINGLE_FOLLOWUPS[1],
    k: 10,
    allow_feedback_capture: false,
    history: [
      { role: 'user', content: 'CS 6140 讲什么？' },
      { role: 'assistant', content: answerText(alias.lines) },
    ],
    context_course_ids: ['c-cs-6140'],
  });
});

it('查看 in an answer opens that course with its ID', async () => {
  const api = world();
  page('/');
  await ask('CS 6140 讲什么？');
  await answered();
  await userEvent.click(screen.getByRole('button', { name: '查看 CS 6140' }));
  expect(where()).toBe('/course/CS-6140');
  expect(stateOf()).toEqual({ courseId: 'c-cs-6140' });
  expect(
    await screen.findByRole('heading', { name: 'Machine Learning' }),
  ).toBeInTheDocument();
  expect(api.count('GET', '/resolve/course')).toBe(0);
});

it('with the opt-in ticked, an answer’s vote goes to /feedback as exactly its receipt and the rating, and the opt-in stays ticked', async () => {
  const api = world((call) =>
    call.path === '/chat' ? stream(receipt.lines) : undefined,
  );
  page(
    '/',
    seededQueryClient({
      config: { answer_feedback_enabled: true, login_available: true },
    }),
  );
  await userEvent.click(
    await screen.findByRole('checkbox', { name: CAPTURE_LABEL }),
  );
  await ask(receipt.request.body.query);
  await userEvent.click(await screen.findByRole('button', { name: '有帮助' }));
  expect(
    await screen.findByText('反馈已保存，仅记录此回答的一条最新评价。'),
  ).toBeInTheDocument();
  expect(chats(api.calls)[0]).toMatchObject({ allow_feedback_capture: true });
  const sent = api.calls.filter((call) => call.path === '/feedback');
  expect(sent.map((call) => [call.method, call.body])).toEqual([
    ['POST', votes.responses[0]!.request],
  ]);
  // As in Streamlit, the answers after it are saved until it is unticked (R3e plan 9): asking does not untick it.
  expect(screen.getByRole('checkbox', { name: CAPTURE_LABEL })).toBeChecked();
});

it('without the opt-in, a question does not ask to save its answer, and the answer has nothing to vote on', async () => {
  const api = world((call) =>
    call.path === '/chat' ? stream(receipt.lines) : undefined,
  );
  const client = seededQueryClient({
    config: { answer_feedback_enabled: true, login_available: true },
  });
  // The privacy words are known before the search state starts (as when the shell mounts again on a warm cache), so
  // the opt-in is offered from the first render and its default is what shows: were they still on their way, the
  // render that finds no notice would clear it anyway (the project's mutation M12).
  client.setQueryData(privacyQuery.queryKey, privacy.body);
  page('/', client);
  expect(
    await screen.findByRole('checkbox', { name: CAPTURE_LABEL }),
  ).not.toBeChecked();
  await ask(receipt.request.body.query);
  await answered();
  // Long enough for a receipt to be checked, had the turn been one to vote on.
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 50));
  });
  expect(screen.queryByRole('button', { name: '有帮助' })).toBeNull();
  expect(chats(api.calls)[0]).toMatchObject({ allow_feedback_capture: false });
});

it('once /privacy can no longer be read, the opt-in is gone from the page and nothing is saved unseen (review A32)', async () => {
  let privacyGone = false;
  const api = world((call) =>
    call.path === '/chat'
      ? stream(receipt.lines)
      : call.path === '/privacy' && privacyGone
        ? apiError(404, 'not_found', 'Not found')
        : undefined,
  );
  const { client } = page(
    '/',
    seededQueryClient({
      config: { answer_feedback_enabled: true, login_available: true },
    }),
  );
  await userEvent.click(
    await screen.findByRole('checkbox', { name: CAPTURE_LABEL }),
  );
  privacyGone = true;
  await act(() => client.invalidateQueries({ queryKey: ['privacy'] }));
  await waitFor(() =>
    expect(
      screen.queryByRole('checkbox', { name: CAPTURE_LABEL }),
    ).not.toBeInTheDocument(),
  );
  await ask(receipt.request.body.query);
  await waitFor(() => expect(chats(api.calls)).toHaveLength(1));
  expect(chats(api.calls)[0]).toMatchObject({ allow_feedback_capture: false });
});

it('unticking the opt-in stops saving the answers after it', async () => {
  const api = world((call) =>
    call.path === '/chat' ? stream(receipt.lines) : undefined,
  );
  page(
    '/',
    seededQueryClient({
      config: { answer_feedback_enabled: true, login_available: true },
    }),
  );
  const box = await screen.findByRole('checkbox', { name: CAPTURE_LABEL });
  await userEvent.click(box);
  expect(box).toBeChecked();
  await userEvent.click(box);
  expect(box).not.toBeChecked();
  await ask(receipt.request.body.query);
  await waitFor(() => expect(chats(api.calls)).toHaveLength(1));
  expect(chats(api.calls)[0]).toMatchObject({ allow_feedback_capture: false });
});

it('an old ?course= link opens the course’s page in its place, so Back goes where the student was', async () => {
  const api = world();
  page(['/compare', '/?course=CS-6140']);
  await waitFor(() => expect(where()).toBe('/course/CS-6140'));
  expect(
    await screen.findByRole('heading', { name: 'Machine Learning' }),
  ).toBeInTheDocument();
  expect(api.calls.map(asked)).toContain('GET /resolve/course?ref=CS-6140');
  await userEvent.click(screen.getByRole('button', { name: 'back' }));
  expect(where()).toBe('/compare');
});

it.each(['%20%20', '.', '..'])(
  'a ?course= of %s stays on the search page (no address can carry it)',
  async (ref) => {
    const api = world();
    page(`/?course=${ref}`);
    await landed();
    expect(where()).toBe(`/?course=${ref}`);
    expect(api.count('GET', '/resolve/course')).toBe(0);
  },
);

it('a ?course= written twice counts by its last value, as in Streamlit', async () => {
  world();
  page('/?course=CS-5800&course=CS-6140');
  await waitFor(() => expect(where()).toBe('/course/CS-6140'));
});

it.each([
  ['CS%206140', '/course/CS-6140', 'CS-6140'],
  [
    '%E6%9C%BA%E5%99%A8%E5%AD%A6%E4%B9%A0',
    '/course/%E6%9C%BA%E5%99%A8%E5%AD%A6%E4%B9%A0',
    '机器学习',
  ],
  ['CS%23%3F6140', '/course/CS%23%3F6140', 'CS#?6140'],
])(
  'a ?course= of %s opens an address that carries it whole, and that is what is looked up (review B32)',
  async (ref, path, sent) => {
    const api = world();
    page(`/?course=${ref}`);
    await waitFor(() => expect(where()).toBe(path));
    await waitFor(() => expect(api.count('GET', '/resolve/course')).toBe(1));
    const lookup = api.calls.find((call) => call.path === '/resolve/course')!;
    expect(new URLSearchParams(lookup.search).get('ref')).toBe(sent);
  },
);

it('a return from Google is the login’s: the course in its address is not opened', async () => {
  const api = world();
  page('/?code=abc&state=xyz&course=CS-6140');
  expect(
    await screen.findByText('登录没有完成，请重新登录。'),
  ).toBeInTheDocument();
  await waitFor(() => expect(where()).toBe('/'));
  expect(api.count('GET', '/resolve/course')).toBe(0);
});

it('asks nothing for the page until it is known who is looking', async () => {
  const me = held();
  const api = world((call) =>
    call.path === '/auth/me' ? me.response : undefined,
  );
  const client = createQueryClient();
  client.setQueryData(configQuery.queryKey, {
    answer_feedback_enabled: false,
    login_available: true,
  });
  // The top bar's count is the same for everyone and goes at once; this is about the page's own requests.
  client.setQueryData(readyQuery.queryKey, SEEDED_READY);
  page('/', client);
  await waitFor(() => expect(api.calls.map(asked)).toEqual(['GET /auth/me']));
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 20));
  });
  expect(api.calls.map(asked)).toEqual(['GET /auth/me']);
  // Nor does it say what a guest can do before it knows there is one.
  expect(screen.queryByText(GUEST_NOTE)).toBeNull();
  me.answer(apiError(401, 'unauthorized', 'Not signed in'));
  await landed();
  expect(api.calls.map(asked).sort()).toEqual(
    ['GET /auth/me', ...LANDING].sort(),
  );
  expect(screen.getByText(GUEST_NOTE)).toBeInTheDocument();
});

it('a question asked before /auth/me answers stays when it says who was looking all along', async () => {
  const me = held();
  const api = world((call) =>
    call.path === '/auth/me' ? me.response : undefined,
  );
  const client = createQueryClient();
  client.setQueryData(configQuery.queryKey, {
    answer_feedback_enabled: false,
    login_available: true,
  });
  page('/', client);
  await ask('CS 6140 讲什么？');
  await answered();
  me.answer(
    json({
      user_id: member.userId,
      email: member.email,
      display_name: null,
      contribution_count: 0,
    }),
  );
  // Known now: the ask box asks for the privacy words.
  await waitFor(() => expect(api.count('GET', '/privacy')).toBe(1));
  expect(
    screen.getByRole('region', { name: '第 1 轮问答' }),
  ).toBeInTheDocument();
});

it('says what a guest can do, and nothing of it to a member', async () => {
  world();
  page('/', seededQueryClient({ viewer: member }));
  await landed();
  expect(screen.queryByText(GUEST_NOTE)).not.toBeInTheDocument();
});

it('a program list that cannot be read says so, and the landing’s retry asks it again', async () => {
  let down = true;
  const api = world((call) =>
    call.path === '/programs' && down
      ? apiError(503, 'service_unavailable', 'down')
      : undefined,
  );
  page('/');
  expect(await screen.findByText(PROGRAMS_UNAVAILABLE)).toBeInTheDocument();
  expect(screen.getByText('部分内容暂时没加载出来。')).toBeInTheDocument();
  expect(combobox('项目')).toBeNull();
  // Featured only once the list says they are there.
  expect(
    api.calls
      .filter((call) => call.path !== '/programs')
      .map(asked)
      .sort(),
  ).toEqual(['GET /coop', 'GET /privacy']);
  down = false;
  await userEvent.click(screen.getByRole('button', { name: '重新加载' }));
  await landed();
  expect(combobox('项目')).toBeInTheDocument();
  expect(screen.queryByText(PROGRAMS_UNAVAILABLE)).not.toBeInTheDocument();
  expect(api.count('GET', '/programs')).toBe(2);
});

it('a program list asked again after a definite failure does not say it cannot be read while the answer is on its way', async () => {
  // TanStack keeps a query that once had data in its error state while it tries again; only then is there a
  // difference between a failure and a try on its way.
  let list: 'ok' | 'gone' | 'held' = 'ok';
  const later = held();
  world((call) =>
    call.path !== '/programs' || list === 'ok'
      ? undefined
      : list === 'gone'
        ? apiError(404, 'not_found', 'Not found')
        : later.response,
  );
  const { client } = page('/');
  await landed();
  list = 'gone';
  await act(() =>
    client.invalidateQueries({
      queryKey: programListQuery.queryKey,
      exact: true,
    }),
  );
  expect(await screen.findByText(PROGRAMS_UNAVAILABLE)).toBeInTheDocument();
  list = 'held';
  act(() => {
    void client.invalidateQueries({
      queryKey: programListQuery.queryKey,
      exact: true,
    });
  });
  await waitFor(() =>
    expect(screen.queryByText(PROGRAMS_UNAVAILABLE)).toBeNull(),
  );
  later.answer(json(programRows));
  await waitFor(() => expect(combobox('项目')).toBeInTheDocument());
});

it('a question goes with the program and the exact plan chosen; the selector offers only the checked plans', async () => {
  const api = world();
  page('/');
  await landed();
  expect(combobox('方案')).toBeNull();
  await choose('项目', CS_PROGRAM);
  expect(screen.getByText(PROGRAM_NOTE)).toBeInTheDocument();
  await userEvent.click(combobox('方案')!);
  expect(
    screen.getAllByRole('option').map((option) => option.textContent),
  ).toEqual([
    PLAN_PLACEHOLDER,
    ALIGN_PLAN,
    'boston · Catalog 2026-2027 · 普通 MS · 共同部分／未限定 concentration',
    'boston · Catalog 2025-2026 · 普通 MS · 共同部分／未限定 concentration',
  ]);
  await userEvent.click(screen.getByRole('option', { name: ALIGN_PLAN }));
  expect(combobox('方案')).toHaveTextContent(ALIGN_PLAN);
  expect(screen.getByText(PLAN_NOTE)).toBeInTheDocument();
  expect(screen.queryByText(PROGRAM_NOTE)).not.toBeInTheDocument();
  await ask('第一学期选什么？');
  await waitFor(() => expect(chats(api.calls)).toHaveLength(1));
  expect(chats(api.calls)[0]).toMatchObject({
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
  // cs-ms was asked once, for the landing; the selector reads the same answer.
  expect(api.count('GET', '/programs/cs-ms')).toBe(1);
});

it('while the program list cannot be read, a question carries no program or plan, as the page shows none (review A32)', async () => {
  let listGone = false;
  const api = world((call) =>
    call.path === '/programs' && listGone
      ? apiError(404, 'not_found', 'Not found')
      : undefined,
  );
  const { client } = page('/');
  await landed();
  await choose('项目', CS_PROGRAM);
  await choose('方案', ALIGN_PLAN);
  listGone = true;
  await act(() =>
    client.invalidateQueries({
      queryKey: programListQuery.queryKey,
      exact: true,
    }),
  );
  expect(await screen.findByText(PROGRAMS_UNAVAILABLE)).toBeInTheDocument();
  expect(combobox('项目')).toBeNull();
  expect(combobox('方案')).toBeNull();
  await ask('第一学期选什么？');
  await waitFor(() => expect(chats(api.calls)).toHaveLength(1));
  expect(chats(api.calls)[0]).not.toHaveProperty('program_id');
  expect(chats(api.calls)[0]).not.toHaveProperty('plan');
});

it('a plan refusal clears the plan on the page, keeps the program and asks for its plans again', async () => {
  const api = world((call) =>
    call.path === '/chat'
      ? json(
          {
            detail: '固定的中文说明',
            error_type: 'conflict',
            status_code: 409,
            reason: 'plan_stale',
          },
          409,
        )
      : undefined,
  );
  page('/');
  await landed();
  await choose('项目', CS_PROGRAM);
  await choose('方案', ALIGN_PLAN);
  await ask('第一学期选什么？');
  expect(
    await screen.findByText(/所选方案的范围或内容版本已变化/, {
      selector: '[data-kind="failure"]',
    }),
  ).toBeInTheDocument();
  expect(combobox('方案')).toHaveTextContent(PLAN_PLACEHOLDER);
  expect(combobox('项目')).toHaveTextContent(CS_PROGRAM);
  expect(screen.getByText(PROGRAM_NOTE)).toBeInTheDocument();
  await waitFor(() => expect(api.count('GET', '/programs/cs-ms')).toBe(2));
});

it('a plan list that changed under the choice clears it and says so', async () => {
  world();
  const { client } = page('/');
  await landed();
  await choose('项目', CS_PROGRAM);
  await choose('方案', ALIGN_PLAN);
  act(() =>
    client.setQueryData(
      curriculumQuery(CS).queryKey,
      csBody({ ...revisions, [STANDARD]: 'f'.repeat(64) }),
    ),
  );
  expect(await screen.findByText(PLAN_REVISED)).toBeInTheDocument();
  expect(combobox('方案')).toHaveTextContent(PLAN_PLACEHOLDER);
  await choose('方案', ALIGN_PLAN);
  expect(screen.queryByText(PLAN_REVISED)).not.toBeInTheDocument();
});

it('a plan list that can no longer be read takes the choice and the selector, and says so', async () => {
  let gone = false;
  world((call) =>
    call.path === '/programs/cs-ms' && gone
      ? apiError(404, 'not_found', 'Program not found')
      : undefined,
  );
  const { client } = page('/');
  await landed();
  await choose('项目', CS_PROGRAM);
  await choose('方案', ALIGN_PLAN);
  gone = true;
  await act(() =>
    client.invalidateQueries({ queryKey: curriculumQuery(CS).queryKey }),
  );
  expect(await screen.findByText(PLANS_UNAVAILABLE)).toBeInTheDocument();
  expect(combobox('方案')).toBeNull();
  expect(screen.getByText(PROGRAM_NOTE)).toBeInTheDocument();
  // Back with the same plans: the choice went with the list, and nothing says the plans changed.
  gone = false;
  await act(() =>
    client.invalidateQueries({ queryKey: curriculumQuery(CS).queryKey }),
  );
  await waitFor(() =>
    expect(combobox('方案')).toHaveTextContent(PLAN_PLACEHOLDER),
  );
  expect(screen.queryByText(PLAN_REVISED)).not.toBeInTheDocument();
});

it('a program list that comes but cannot be read says so as well, and takes the choice’s selector (recheck 1)', async () => {
  let list: unknown = programRows;
  const api = world((call) =>
    call.path === '/programs' ? json(list) : undefined,
  );
  const { client } = page('/');
  await landed();
  await choose('项目', CS_PROGRAM);
  // The same program twice: parseProgramList cannot read it.
  list = [programRows[1], programRows[1]];
  await act(() =>
    client.invalidateQueries({ queryKey: programListQuery.queryKey }),
  );
  expect(await screen.findByText(PROGRAMS_UNAVAILABLE)).toBeInTheDocument();
  expect(combobox('项目')).toBeNull();
  await ask('CS 6140 讲什么？');
  await waitFor(() => expect(chats(api.calls)).toHaveLength(1));
  expect(chats(api.calls)[0]).not.toHaveProperty('program_id');
});

it('an empty program list shows no selectors, and says nothing failed (R0 3 ①, review B32)', async () => {
  world((call) => (call.path === '/programs' ? json([]) : undefined));
  page('/');
  expect(
    await screen.findByRole('button', { name: '去看看' }),
  ).toBeInTheDocument();
  expect(combobox('项目')).toBeNull();
  expect(screen.queryByText(PROGRAMS_UNAVAILABLE)).toBeNull();
});

it('a program no longer listed goes from the choice', async () => {
  world();
  const { client } = page('/');
  await landed();
  await choose('项目', CS_PROGRAM);
  act(() =>
    client.setQueryData(
      programListQuery.queryKey,
      programRows.filter((row) => row.program_id !== CS),
    ),
  );
  await waitFor(() => expect(combobox('项目')).toHaveTextContent('不指定'));
  expect(combobox('方案')).toBeNull();
  expect(screen.queryByText(PROGRAM_NOTE)).not.toBeInTheDocument();
});

it('the program and plan chosen stay on a course page and after it (review B32)', async () => {
  world();
  page('/');
  await landed();
  await choose('项目', CS_PROGRAM);
  await choose('方案', ALIGN_PLAN);
  await userEvent.click(screen.getByRole('button', { name: '查看 CS 5010' }));
  await waitFor(() => expect(where()).toBe('/course/CS-5010'));
  expect(combobox('项目')).toHaveTextContent(CS_PROGRAM);
  expect(combobox('方案')).toHaveTextContent(ALIGN_PLAN);
  await userEvent.click(screen.getByRole('link', { name: '回到课程搜索' }));
  await waitFor(() => expect(where()).toBe('/'));
  expect(combobox('项目')).toHaveTextContent(CS_PROGRAM);
  expect(combobox('方案')).toHaveTextContent(ALIGN_PLAN);
});

it('a question on its way goes on while the student looks at another page (plan 3, review B32)', async () => {
  const chat = held();
  const api = world((call) =>
    call.path === '/chat' ? chat.response : undefined,
  );
  page('/');
  await landed();
  await ask('CS 6140 讲什么？');
  await waitFor(() => expect(chats(api.calls)).toHaveLength(1));
  await userEvent.click(
    within(screen.getByRole('navigation', { name: '主导航' })).getByRole(
      'link',
      { name: /课程对比/ },
    ),
  );
  await waitFor(() => expect(where()).toBe('/compare'));
  chat.answer(stream(alias.lines));
  await userEvent.click(screen.getByRole('button', { name: 'back' }));
  await waitFor(() => expect(where()).toBe('/'));
  expect(await answered()).toBeInTheDocument();
  expect(chats(api.calls)).toHaveLength(1);
});

it('a logout on the page empties the conversation, the choices and the opt-in (review B32)', async () => {
  world((call) =>
    call.path === '/auth/logout'
      ? new Response(null, { status: 204 })
      : undefined,
  );
  page(
    '/',
    seededQueryClient({
      viewer: member,
      config: { answer_feedback_enabled: true, login_available: true },
    }),
  );
  await landed();
  await choose('项目', CS_PROGRAM);
  await choose('方案', ALIGN_PLAN);
  await userEvent.click(screen.getByRole('checkbox', { name: CAPTURE_LABEL }));
  await ask('CS 6140 讲什么？');
  await answered();
  await userEvent.click(
    screen.getAllByRole('button', { name: '退出登录' })[0]!,
  );
  await landed();
  expect(screen.queryByText('CS 6140 讲什么？')).not.toBeInTheDocument();
  expect(combobox('项目')).toHaveTextContent('不指定');
  expect(combobox('方案')).toBeNull();
  expect(
    screen.getByRole('checkbox', { name: CAPTURE_LABEL }),
  ).not.toBeChecked();
  expect(screen.getByText(GUEST_NOTE)).toBeInTheDocument();
});

it('the same member with a new contribution count keeps the conversation and the choices (review B32)', async () => {
  world();
  const { client } = page('/', seededQueryClient({ viewer: member }));
  await landed();
  await choose('项目', CS_PROGRAM);
  await ask('CS 6140 讲什么？');
  await answered();
  // What a Co-op upload's 201 does to the session (useSession's contributed): the same person, one more credited.
  const credited: Member = { ...member, contributionCount: 1 };
  act(() => {
    client.setQueryData(meQuery.queryKey, credited);
  });
  expect((await screen.findAllByText('贡献数：1')).length).toBeGreaterThan(0);
  // Long enough for a reset after that render to have come, had there been one.
  await act(() => new Promise((resolve) => setTimeout(resolve, 20)));
  expect(screen.getByText('CS 6140 讲什么？')).toBeInTheDocument();
  expect(combobox('项目')).toHaveTextContent(CS_PROGRAM);
});

it('the landing’s Co-op is asked as the member looking, who is shown what a guest is not (review B32)', async () => {
  const unlocked = { ...coop.body[0]!, salary_range_usd: '40–45 USD/hour' };
  const api = world((call) =>
    call.path === '/coop' ? json([unlocked]) : undefined,
  );
  page('/', seededQueryClient({ viewer: { ...member, contributionCount: 2 } }));
  expect(await screen.findByText(unlocked.company)).toBeInTheDocument();
  expect(screen.queryByText(/你分享的经验公开后解锁/)).toBeNull();
  expect(api.count('GET', '/coop')).toBe(1);
});

it('has no DOM axe violations with the landing, and with a conversation', async () => {
  world();
  const { container } = page('/');
  await landed();
  const rules = { rules: { 'color-contrast': { enabled: false } } };
  expect((await axe(container, rules)).violations).toEqual([]);
  await ask('CS 6140 讲什么？');
  await answered();
  expect((await axe(container, rules)).violations).toEqual([]);
});

// The ask box is held at the window's bottom edge now, so a question asked comes into view where its answer is read
// below it (R6, the user's choice of 10-29).
it('each question asked on the search page comes into view; coming back to the page without asking scrolls nowhere', async () => {
  world();
  page('/');
  const into = vi.spyOn(Element.prototype, 'scrollIntoView');
  await ask('CS 6140 讲什么？');
  await answered();
  expect(into.mock.contexts.at(-1)).toHaveTextContent('CS 6140 讲什么？');
  expect(into.mock.calls.at(-1)).toEqual([{ block: 'start' }]);
  // A follow-up is asked on this page too.
  const [followUp] = within(
    screen.getByRole('group', { name: '接着问' }),
  ).getAllByRole('button');
  await userEvent.click(followUp!);
  await waitFor(() =>
    expect(into.mock.contexts.at(-1)).toHaveTextContent(followUp!.textContent!),
  );
  expect(screen.getAllByRole('region', { name: /轮问答$/ })).toHaveLength(2);
  into.mockClear();
  await userEvent.click(
    screen.getAllByRole('button', { name: '查看 CS 6140' })[0]!,
  );
  await screen.findByRole('heading', { name: 'Machine Learning' });
  await userEvent.click(screen.getByRole('link', { name: '回到课程搜索' }));
  expect(where()).toBe('/');
  await screen.findByRole('region', { name: '第 2 轮问答' });
  expect(into).not.toHaveBeenCalled();
});

// What the page has seen goes down with the conversation: back on the page with one, a logout empties it, and the
// first question asked after that comes into view as well (R6).
it('after a logout empties the conversation the page came back to, the next question asked comes into view', async () => {
  world((call) =>
    call.path === '/auth/logout'
      ? new Response(null, { status: 204 })
      : undefined,
  );
  page('/', seededQueryClient({ viewer: member }));
  await landed();
  await ask('CS 6140 讲什么？');
  await answered();
  // Away and back: the page is drawn anew, with the conversation it had.
  await userEvent.click(
    screen.getAllByRole('button', { name: '查看 CS 6140' })[0]!,
  );
  await screen.findByRole('heading', { name: 'Machine Learning' });
  await userEvent.click(screen.getByRole('link', { name: '回到课程搜索' }));
  await screen.findByRole('region', { name: '第 1 轮问答' });
  await userEvent.click(
    screen.getAllByRole('button', { name: '退出登录' })[0]!,
  );
  await landed();
  const into = vi.spyOn(Element.prototype, 'scrollIntoView');
  await ask('CS 5800 讲什么？');
  await answered();
  expect(into.mock.contexts.at(-1)).toHaveTextContent('CS 5800 讲什么？');
});

it('while the ask box is on the page, html carries its height (--ask-bar-height), and lets it go with the box', async () => {
  world();
  vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(152);
  page('/');
  const root = document.documentElement;
  await waitFor(() =>
    expect(root.style.getPropertyValue('--ask-bar-height')).toBe('152px'),
  );
  await userEvent.click(
    within(screen.getByRole('navigation', { name: '主导航' })).getByRole(
      'link',
      { name: /课程对比/ },
    ),
  );
  expect(screen.queryByRole('form', { name: '提问' })).toBeNull();
  expect(root.style.getPropertyValue('--ask-bar-height')).toBe('');
});

// Measured once when it mounts, the box was taken as lower than it became (section 40 item 8); jsdom can see both
// ways it is measured again (review B34).
it('the ask box is measured again after it draws again, not only when it mounts', async () => {
  world();
  let tall = 152;
  vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockImplementation(
    () => tall,
  );
  page('/');
  const height = () =>
    document.documentElement.style.getPropertyValue('--ask-bar-height');
  await waitFor(() => expect(height()).toBe('152px'));
  tall = 221;
  await userEvent.type(screen.getByRole('textbox', { name: '课程问题' }), 'C');
  await waitFor(() => expect(height()).toBe('221px'));
});

it('a resize the ResizeObserver reports is measured too', async () => {
  const observed: Element[] = [];
  let report: (() => void) | undefined;
  const stub = window.ResizeObserver;
  window.ResizeObserver = class {
    constructor(callback: () => void) {
      report = callback;
    }
    observe(element: Element) {
      observed.push(element);
    }
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
  try {
    world();
    let tall = 152;
    vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockImplementation(
      () => tall,
    );
    page('/');
    const height = () =>
      document.documentElement.style.getPropertyValue('--ask-bar-height');
    await waitFor(() => expect(height()).toBe('152px'));
    expect(observed).toContain(screen.getByRole('form', { name: '提问' }));
    tall = 193;
    act(() => report?.());
    expect(height()).toBe('193px');
  } finally {
    window.ResizeObserver = stub;
  }
});

// Only a course page's question opens the search page; one asked on it adds no entry to the history (review B34).
it('a question asked on the search page adds no entry to the history', async () => {
  world();
  page(['/programs', '/']);
  await landed();
  await ask('CS 6140 讲什么？');
  await answered();
  await userEvent.click(screen.getByRole('button', { name: 'back' }));
  expect(where()).toBe('/programs');
});

// A follow-up's button goes with the turn it was under, so focus fell to the body (review A34): it goes to the
// conversation, which stays, without scrolling it away from the question brought into view.
it('after a follow-up pressed with the keyboard, focus is on the conversation', async () => {
  world();
  page('/');
  const user = userEvent.setup();
  await ask('CS 6140 讲什么？');
  const [followUp] = within(await answered()).getAllByRole('button');
  followUp!.focus();
  const focus = vi.spyOn(HTMLElement.prototype, 'focus');
  await user.keyboard('{Enter}');
  await waitFor(() =>
    expect(screen.getAllByRole('region', { name: /轮问答$/ })).toHaveLength(2),
  );
  const conversation = screen.getByRole('group', { name: '对话' });
  expect(conversation).toHaveFocus();
  expect(focus.mock.calls[focus.mock.contexts.indexOf(conversation)]).toEqual([
    { preventScroll: true },
  ]);
});

// Focus in the ask box stays there, for the first question, which takes the landing away, as for those after it: the
// conversation takes it only from a sample question's or a follow-up's button, which goes, and when it was left on
// nothing (the focus rule of 10-25). Sent with the button too, which the empty box disables (recheck 1 of round 34).
it.each([
  ['Enter', ask],
  ['the send button', askWithButton],
])(
  'a question asked in the ask box with %s, the first as those after it, leaves focus in the box',
  async (_, send) => {
    world();
    page('/');
    await landed();
    const box = screen.getByRole('textbox', { name: '课程问题' });
    const focus = vi.spyOn(HTMLElement.prototype, 'focus');
    await send('CS 6140 讲什么？');
    await answered();
    expect(box).toHaveFocus();
    await send('CS 5800 讲什么？');
    await waitFor(() =>
      expect(screen.getAllByRole('region', { name: /轮问答$/ })).toHaveLength(
        2,
      ),
    );
    await answered();
    expect(box).toHaveFocus();
    expect(focus.mock.contexts).not.toContain(
      screen.getByRole('group', { name: '对话' }),
    );
  },
);

// Safari's click leaves focus where it was, and a screen reader may press a button without focus on it: the buttons
// still go with what they were in, so the conversation takes focus from them all the same (recheck 1 of round 34).
it('a sample question or a follow-up pressed without focus on it still gives focus to the conversation', async () => {
  world();
  page('/');
  await landed();
  const main = screen.getByRole('main');
  main.focus();
  fireEvent.click(screen.getByRole('button', { name: 'CS 5800' }));
  const followUps = await answered();
  const conversation = screen.getByRole('group', { name: '对话' });
  expect(conversation).toHaveFocus();
  main.focus();
  fireEvent.click(within(followUps).getAllByRole('button')[0]!);
  await waitFor(() =>
    expect(screen.getAllByRole('region', { name: /轮问答$/ })).toHaveLength(2),
  );
  expect(conversation).toHaveFocus();
  // What the button said goes with its question: one asked in the ask box after it leaves focus in the box.
  await answered();
  await ask('CS 5800 讲什么？');
  await waitFor(() =>
    expect(screen.getAllByRole('region', { name: /轮问答$/ })).toHaveLength(3),
  );
  expect(screen.getByRole('textbox', { name: '课程问题' })).toHaveFocus();
});

// Out of the form, the opt-in and its notice, or the line that nothing is saved, are a landmark of their own, so
// nothing on the search page is outside one (recheck 1 of round 34). axe's region rule is given the body itself. Given
// a container, as RTL's, the rule does not apply (its selector is `body *`, and there is no body under the container),
// so the test would pass whatever is outside a landmark (recheck 2). Given the html element, which is not in the body,
// vitest-axe copies the page into the body and leaves the copy behind for the next test.
it.each([
  ['on', true],
  ['off', false],
])(
  'with answer feedback %s, nothing on the search page is outside a landmark',
  async (_, feedback) => {
    world();
    page(
      '/',
      seededQueryClient({
        config: { answer_feedback_enabled: feedback, login_available: true },
      }),
    );
    await landed();
    expect(
      await screen.findByRole('region', { name: CAPTURE_REGION }),
    ).toHaveTextContent(feedback ? CAPTURE_LABEL : CAPTURE_OFF);
    expect(
      (await axe(document.body, { runOnly: ['region'] })).violations,
    ).toEqual([]);
  },
);
