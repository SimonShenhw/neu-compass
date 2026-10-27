import { act, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it } from 'vitest';
import { curriculumQuery } from '../api/programs';
import { configQuery, createQueryClient } from '../api/queries';
import type { Member } from '../api/queries';
import { readyQuery } from '../api/ready';
import ready from '../fixtures/programs/policies-cs-ms-standard-ready.json';
import { PLAN_PLACEHOLDER } from '../models/programFormat';
import { PLAN_LINK_NOTICES, programNotFound } from '../models/programLinks';
import { apiError, asked, held, json } from '../test/fakeApi';
import type { Call } from '../test/fakeApi';
import { SEEDED_READY, seededQueryClient } from '../test/withApi';
import { CHECKING_LINK, PLAN_REVISED_LINE } from './ProgramsRoute';
import {
  CS,
  STANDARD,
  choose,
  combobox,
  csBody,
  page,
  revisions,
  stateOf,
  where,
  world,
} from './searchRouteTestUtils';

const BRIDGE = 'cs-ms-boston-2026-2027-bridge';
const PLAN = '选择目录版本与路径';
const STANDARD_PLAN =
  'boston · Catalog 2026-2027 · 普通 MS · 共同部分／未限定 concentration';
const ALIGN_PLAN =
  'boston · Catalog 2026-2027 · Align · 共同部分／未限定 concentration';
const NOT_FOUND = '找不到这个培养方案，可能已经下线。';
const CURRICULUM = `/programs/${CS}`;
const POLICIES = `/programs/${CS}/plans/${STANDARD}/policies`;
const member: Member = {
  kind: 'member',
  userId: 'u-1',
  email: 'student@example.edu',
  displayName: null,
  contributionCount: 0,
};
// The standard plan's policy evidence, ready at its current version.
const policies = (call: Call) =>
  call.path === POLICIES ? json(ready.body) : undefined;
const down = () => apiError(503, 'service_unavailable', 'Service unavailable');
const opened = () =>
  screen.findByRole('combobox', { name: (name) => name.startsWith(PLAN) });
const shared = () =>
  document.querySelector('[data-kind="share_url"]')?.textContent;
const linkNotice = () => screen.getByRole('status', { name: '分享链接' });
// Ready evidence links each policy's official source.
const evidence = () => screen.findAllByText('官方政策来源');
// A plan link to cs-ms's standard plan, as the share box writes it.
const planLink = (over: Record<string, string> = {}) =>
  '/?' +
  new URLSearchParams({
    plan_v: '1',
    program: CS,
    plan: STANDARD,
    campus: 'boston',
    catalog_year: '2026-2027',
    pathway: 'standard',
    concentration: 'null',
    plan_revision: revisions[STANDARD]!,
    ...over,
  }).toString();

it('the list opens a program at an address of its own, titled as the program list', async () => {
  const api = world();
  page('/programs');
  await userEvent.click(
    await screen.findByRole('button', { name: '查看 CS 的课程表' }),
  );
  expect(where()).toBe('/programs/cs-ms');
  expect(await opened()).toBeInTheDocument();
  expect(document.title).toBe('培养方案 · NEU-Compass');
  expect(api.count('GET', '/programs')).toBe(1);
  expect(api.count('GET', CURRICULUM)).toBe(1);
});

it('a list that cannot be read loads again, and focus goes to the list', async () => {
  let first = true;
  world((call) => {
    if (call.path !== '/programs' || !first) return undefined;
    first = false;
    return down();
  });
  page('/programs');
  await userEvent.click(
    await screen.findByRole('button', { name: '重新加载' }),
  );
  expect(
    await screen.findByRole('button', { name: '查看 CS 的课程表' }),
  ).toBeInTheDocument();
  expect(screen.getByRole('region', { name: '培养方案列表' })).toHaveFocus();
});

it('choosing a plan reads its policy evidence, and the share box gives the program, then the plan', async () => {
  const api = world(policies);
  page('/programs/cs-ms');
  await opened();
  expect(shared()).toBe('http://127.0.0.1:5173/programs/cs-ms');
  await choose(PLAN, STANDARD_PLAN);
  expect(await evidence()).not.toHaveLength(0);
  expect(api.count('GET', POLICIES)).toBe(1);
  expect(shared()).toBe(
    `http://127.0.0.1:5173/?plan_v=1&program=cs-ms&plan=${STANDARD}&campus=boston&catalog_year=2026-2027&pathway=standard&concentration=null&plan_revision=${revisions[STANDARD]}`,
  );
});

it.each(['/programs', '/programs/cs-ms'])(
  '%s asks nothing until it is known who is looking',
  async (address) => {
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
    page(address, client);
    await waitFor(() => expect(api.calls.map(asked)).toEqual(['GET /auth/me']));
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    expect(api.calls.map(asked)).toEqual(['GET /auth/me']);
    me.answer(apiError(401, 'unauthorized', 'Not signed in'));
    await waitFor(() =>
      expect(api.calls.map(asked)).toContain(`GET ${address}`),
    );
  },
);

it('no policy evidence is asked for before a plan is chosen', async () => {
  const api = world(policies);
  page('/programs/cs-ms');
  await opened();
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 20));
  });
  expect(api.calls.filter((call) => call.path.endsWith('/policies'))).toEqual(
    [],
  );
});

it('「刷新页面内容」 reads the evidence again and shows it as loading, never the answer before it', async () => {
  const later = held();
  let reads = 0;
  world((call) =>
    call.path === POLICIES
      ? ++reads === 1
        ? json(ready.body)
        : later.response
      : undefined,
  );
  page('/programs/cs-ms');
  await opened();
  await choose(PLAN, STANDARD_PLAN);
  expect(await evidence()).not.toHaveLength(0);
  await userEvent.click(
    screen.getAllByRole('button', { name: '刷新页面内容' })[0]!,
  );
  expect(await screen.findByText('正在加载政策证据…')).toBeInTheDocument();
  expect(screen.queryAllByText('官方政策来源')).toHaveLength(0);
  later.answer(json(ready.body));
  expect(await evidence()).not.toHaveLength(0);
});

it('the plan chosen in a program stays through a visit to the list and back', async () => {
  world(policies);
  page('/programs/cs-ms');
  await opened();
  await choose(PLAN, STANDARD_PLAN);
  await userEvent.click(screen.getByRole('button', { name: '所有培养方案' }));
  expect(where()).toBe('/programs');
  await userEvent.click(
    await screen.findByRole('button', { name: '查看 CS 的课程表' }),
  );
  expect(await opened()).toHaveTextContent(STANDARD_PLAN);
});

it('policy evidence read again shows as loading, never the answer before it', async () => {
  const later = held();
  let reads = 0;
  world((call) =>
    call.path === POLICIES
      ? ++reads === 1
        ? json(ready.body)
        : later.response
      : undefined,
  );
  page('/programs/cs-ms');
  await opened();
  await choose(PLAN, STANDARD_PLAN);
  expect(await evidence()).not.toHaveLength(0);
  await choose(PLAN, ALIGN_PLAN);
  await choose(PLAN, STANDARD_PLAN);
  expect(await screen.findByText('正在加载政策证据…')).toBeInTheDocument();
  expect(screen.queryAllByText('官方政策来源')).toHaveLength(0);
  later.answer(json(ready.body));
  expect(await evidence()).not.toHaveLength(0);
});

it('refreshing drops the program’s answer, so a failed read shows no older curriculum, and the choice goes', async () => {
  let failing = false;
  world((call) =>
    call.path === CURRICULUM && failing ? down() : policies(call),
  );
  page('/programs/cs-ms');
  await opened();
  await choose(PLAN, STANDARD_PLAN);
  failing = true;
  await userEvent.click(
    screen.getByRole('button', { name: '刷新方案及政策证据' }),
  );
  expect(await screen.findByText(/^无法加载课程表。/)).toBeInTheDocument();
  expect(combobox(PLAN)).toBeNull();
  failing = false;
  await userEvent.click(
    screen.getByRole('button', { name: '刷新方案及政策证据' }),
  );
  expect(await opened()).toHaveTextContent(PLAN_PLACEHOLDER);
});

it('a plan list that changed under the choice clears it and says so once, where screen readers hear it too', async () => {
  let changed = false;
  world((call) =>
    call.path === CURRICULUM && changed
      ? json(csBody({ ...revisions, [STANDARD]: 'f'.repeat(64) }))
      : policies(call),
  );
  const { client } = page('/programs/cs-ms');
  await opened();
  await choose(PLAN, STANDARD_PLAN);
  changed = true;
  await act(() =>
    client.invalidateQueries({
      queryKey: curriculumQuery(CS).queryKey,
      exact: true,
    }),
  );
  // R4a's line on the page, and the same words in the status region.
  expect(await screen.findAllByText(PLAN_REVISED_LINE)).toHaveLength(2);
  expect(screen.getByRole('status', { name: '方案更新' })).toHaveTextContent(
    PLAN_REVISED_LINE,
  );
  expect(combobox(PLAN)).toHaveTextContent(PLAN_PLACEHOLDER);
  await choose(PLAN, ALIGN_PLAN);
  expect(screen.queryByText(PLAN_REVISED_LINE)).not.toBeInTheDocument();
  expect(screen.getByRole('status', { name: '方案更新' })).toHaveTextContent(
    '',
  );
});

it('a course row opens the course’s page with its ID', async () => {
  world();
  page('/programs/cs-ms');
  await opened();
  await userEvent.click(screen.getByRole('button', { name: '查看 CS 5010' }));
  expect(where()).toBe('/course/CS-5010');
  expect(stateOf()).toEqual({ courseId: 'c-cs-5010' });
});

it.each(['CS-MS', '-cs', 'x'.repeat(65)])(
  'an address with %s, which is no program ID, says not found and asks nothing',
  async (id) => {
    const api = world();
    page(`/programs/${encodeURIComponent(id)}`);
    expect(await screen.findByText(NOT_FOUND)).toBeInTheDocument();
    expect(
      api.calls.filter((call) => call.path.startsWith('/programs/')),
    ).toEqual([]);
  },
);

it('a program the API does not have says so', async () => {
  world();
  page('/programs/pjm-ms');
  expect(await screen.findByText(NOT_FOUND)).toBeInTheDocument();
});

it('a logout empties the plans chosen', async () => {
  world((call) =>
    call.path === '/auth/logout'
      ? new Response(null, { status: 204 })
      : policies(call),
  );
  page('/programs/cs-ms', seededQueryClient({ viewer: member }));
  await opened();
  await choose(PLAN, STANDARD_PLAN);
  await userEvent.click(
    screen.getAllByRole('button', { name: '退出登录' })[0]!,
  );
  await waitFor(() =>
    expect(combobox(PLAN)).toHaveTextContent(PLAN_PLACEHOLDER),
  );
  expect(where()).toBe('/programs/cs-ms');
});

it.each(['cs-ms', 'CS-MS', 'cs', ' Cs '])(
  '/?program=%j opens the program it names, in place of the address',
  async (ref) => {
    world();
    page(['/compare', `/?program=${encodeURIComponent(ref)}`]);
    await waitFor(() => expect(where()).toBe('/programs/cs-ms'));
    expect(await opened()).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'back' }));
    expect(where()).toBe('/compare');
  },
);

it('a /?program= ref that names no program opens the list and says so', async () => {
  world();
  page('/?program=nope');
  await waitFor(() => expect(where()).toBe('/programs'));
  expect(
    await screen.findByRole('button', { name: '查看 CS 的课程表' }),
  ).toBeInTheDocument();
  // The sentence comes with a second turn of the address, once the list has been read.
  await waitFor(() =>
    expect(linkNotice()).toHaveTextContent(programNotFound('nope')),
  );
  expect(where()).toBe('/programs');
});

it('while the list cannot be read a /?program= ref waits, and loading the list again opens the program', async () => {
  let first = true;
  world((call) => {
    if (call.path !== '/programs' || !first) return undefined;
    first = false;
    return down();
  });
  page('/?program=cs');
  await userEvent.click(
    await screen.findByRole('button', { name: '重新加载' }),
  );
  await waitFor(() => expect(where()).toBe('/programs/cs-ms'));
});

it('a course with a program opens the course, as it did', async () => {
  world();
  page('/?course=CS-5800&program=cs-ms');
  await waitFor(() => expect(where()).toBe('/course/CS-5800'));
});

it('a plan link opens its program and chooses exactly the plan shared, read past the cache', async () => {
  const api = world(policies);
  const client = seededQueryClient();
  // An older answer in the cache, in which the shared plan was at another version.
  client.setQueryData(
    curriculumQuery(CS).queryKey,
    csBody({ ...revisions, [STANDARD]: 'e'.repeat(64) }),
  );
  page(['/compare', planLink()], client);
  await waitFor(() =>
    expect(linkNotice()).toHaveTextContent(PLAN_LINK_NOTICES.ready),
  );
  expect(where()).toBe('/programs/cs-ms');
  expect(combobox(PLAN)).toHaveTextContent(STANDARD_PLAN);
  expect(api.count('GET', CURRICULUM)).toBe(1);
  expect(await evidence()).not.toHaveLength(0);
  await userEvent.click(screen.getByRole('button', { name: 'back' }));
  expect(where()).toBe('/compare');
});

it.each([
  [
    'another version',
    { plan_revision: 'f'.repeat(64) },
    PLAN_LINK_NOTICES.stale,
  ],
  ['gone', { plan: 'cs-ms-gone' }, PLAN_LINK_NOTICES.missing],
  [
    'a draft',
    { plan: BRIDGE, pathway: 'bridge', plan_revision: revisions[BRIDGE]! },
    PLAN_LINK_NOTICES.draft,
  ],
])(
  'a plan link whose plan is %s opens the program with no plan chosen and says why',
  async (_name, over, notice) => {
    world();
    page(planLink(over));
    await waitFor(() => expect(linkNotice()).toHaveTextContent(notice));
    expect(where()).toBe('/programs/cs-ms');
    expect(combobox(PLAN)).toHaveTextContent(PLAN_PLACEHOLDER);
  },
);

it.each([
  [
    'can be trusted no more',
    (body: ReturnType<typeof csBody>) => ({
      ...body,
      plans: [...body.plans, body.plans[0]],
    }),
    PLAN_LINK_NOTICES.unusable,
  ],
  [
    'not there',
    (body: ReturnType<typeof csBody>) => ({
      ...body,
      plan_schema_available: false,
    }),
    PLAN_LINK_NOTICES.unavailable,
  ],
])(
  'a plan link to a program whose plans %s says so',
  async (_name, change, notice) => {
    world((call) =>
      call.path === CURRICULUM ? json(change(csBody())) : undefined,
    );
    page(planLink());
    await waitFor(() => expect(linkNotice()).toHaveTextContent(notice));
    expect(where()).toBe('/programs/cs-ms');
  },
);

it.each([
  ['a key left out', '/?plan_v=1&program=cs-ms'],
  ['a course with it', `${planLink()}&course=CS-5800`],
  ['a key twice', `${planLink()}&plan=${STANDARD}`],
])(
  'a plan link with %s opens the list and says so, neither the course nor the program',
  async (_name, address) => {
    world();
    page(address);
    await waitFor(() => expect(where()).toBe('/programs'));
    expect(linkNotice()).toHaveTextContent(PLAN_LINK_NOTICES.invalid);
  },
);

it('a plan link checked while the API fails for a moment is checked again by 刷新方案及政策证据', async () => {
  let failing = true;
  world((call) =>
    call.path === CURRICULUM && failing ? down() : policies(call),
  );
  page(planLink());
  await waitFor(() =>
    expect(linkNotice()).toHaveTextContent(PLAN_LINK_NOTICES.retry),
  );
  failing = false;
  await userEvent.click(
    screen.getByRole('button', { name: '刷新方案及政策证据' }),
  );
  await waitFor(() =>
    expect(linkNotice()).toHaveTextContent(PLAN_LINK_NOTICES.ready),
  );
  expect(combobox(PLAN)).toHaveTextContent(STANDARD_PLAN);
});

it('an older answer in the cache does not stand in for the fresh read that failed for a moment', async () => {
  world((call) => (call.path === CURRICULUM ? down() : undefined));
  const client = seededQueryClient();
  client.setQueryData(
    curriculumQuery(CS).queryKey,
    csBody({ ...revisions, [STANDARD]: 'e'.repeat(64) }),
  );
  page(planLink(), client);
  await waitFor(() =>
    expect(linkNotice()).toHaveTextContent(PLAN_LINK_NOTICES.retry),
  );
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 20));
  });
  expect(linkNotice()).toHaveTextContent(PLAN_LINK_NOTICES.retry);
});

it('while a plan link is checked the page says so; to a program the API does not have it adds nothing to the page’s own words', async () => {
  const later = held();
  world((call) => (call.path === CURRICULUM ? later.response : undefined));
  page(planLink());
  await waitFor(() => expect(linkNotice()).toHaveTextContent(CHECKING_LINK));
  later.answer(apiError(404, 'not_found', 'Program not found'));
  expect(await screen.findByText(NOT_FOUND)).toBeInTheDocument();
  await waitFor(() => expect(linkNotice()).toHaveTextContent(''));
});

it('the program’s earlier choice does not stand in for the plan a link shares', async () => {
  world();
  // A plan chosen in cs-ms, then a history entry that still has a link to check, to a plan cs-ms no longer has.
  page(
    [
      '/programs/cs-ms',
      {
        pathname: '/programs/cs-ms',
        state: { planQuery: planLink({ plan: 'cs-ms-gone' }).slice(1) },
      },
    ],
    seededQueryClient(),
    0,
  );
  await opened();
  await choose(PLAN, ALIGN_PLAN);
  await userEvent.click(screen.getByRole('button', { name: 'forward' }));
  await waitFor(() =>
    expect(linkNotice()).toHaveTextContent(PLAN_LINK_NOTICES.missing),
  );
  expect(combobox(PLAN)).toHaveTextContent(PLAN_PLACEHOLDER);
});
