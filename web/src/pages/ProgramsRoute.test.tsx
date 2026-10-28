import { QueryObserver } from '@tanstack/react-query';
import type { QueryClient } from '@tanstack/react-query';
import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { ApiError } from '../api/client';
import type { DraftRequest } from '../api/draft';
import { curriculumQuery } from '../api/programs';
import { configQuery, createQueryClient } from '../api/queries';
import type { Member } from '../api/queries';
import { readyQuery } from '../api/ready';
import stale from '../fixtures/draft/draft-409-stale.json';
import unavailable from '../fixtures/draft/draft-409-unavailable.json';
import unusable from '../fixtures/draft/draft-409-unusable.json';
import ready from '../fixtures/programs/policies-cs-ms-standard-ready.json';
import { draftFailureMessage } from '../models/planDraft';
import { PLAN_PLACEHOLDER } from '../models/programFormat';
import { PLAN_LINK_NOTICES, programNotFound } from '../models/programLinks';
import { apiError, asked, held, json } from '../test/fakeApi';
import type { Call } from '../test/fakeApi';
import { SEEDED_READY, seededQueryClient } from '../test/withApi';
import {
  CHECKING_LINK,
  PLAN_REFUSED_LINE,
  PLAN_REVISED_LINE,
} from './ProgramsRoute';
import {
  ALIGN,
  CS,
  STANDARD,
  choose,
  combobox,
  csBody,
  draftAnswer,
  draftChecks,
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

it('a list that cannot be read loads again, and focus goes to the list, without scrolling', async () => {
  let first = true;
  world((call) => {
    if (call.path !== '/programs' || !first) return undefined;
    first = false;
    return down();
  });
  page('/programs');
  const focus = vi.spyOn(HTMLElement.prototype, 'focus');
  await userEvent.click(
    await screen.findByRole('button', { name: '重新加载' }),
  );
  expect(
    await screen.findByRole('button', { name: '查看 CS 的课程表' }),
  ).toBeInTheDocument();
  const list = screen.getByRole('region', { name: '培养方案列表' });
  expect(list).toHaveFocus();
  expect(focus.mock.calls[focus.mock.contexts.indexOf(list)]).toEqual([
    { preventScroll: true },
  ]);
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
  // R4a's line on the page, and the same words in the status region, heard there and not shown twice.
  expect(await screen.findAllByText(PLAN_REVISED_LINE)).toHaveLength(2);
  const status = screen.getByRole('status', { name: '方案更新' });
  expect(status).toHaveTextContent(PLAN_REVISED_LINE);
  expect(within(status).getByText(PLAN_REVISED_LINE)).toHaveClass(
    'visually-hidden',
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

it('/?program= written twice counts by its last value, as Streamlit reads it', async () => {
  world();
  page('/?program=nope&program=cs');
  await waitFor(() => expect(where()).toBe('/programs/cs-ms'));
});

it('a blank /?program= stays on the search page', async () => {
  world();
  page('/?program=%20');
  await moment();
  expect(where()).toBe('/?program=%20');
});

it('a list that reads as no list says so, and a /?program= ref waits for one that does', async () => {
  world((call) =>
    call.path === '/programs' ? json({ nope: true }) : undefined,
  );
  page('/?program=cs');
  expect(
    await screen.findByText('培养方案列表的格式不对，没有显示。'),
  ).toBeInTheDocument();
  await moment();
  expect(where()).toBe('/programs');
  expect(linkNotice()).toHaveTextContent('');
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
  // The entry keeps nothing a reload would show with no plan chosen: the choice says so.
  expect(stateOf()).toBeNull();
  expect(combobox(PLAN)).toHaveTextContent(STANDARD_PLAN);
  expect(api.count('GET', CURRICULUM)).toBe(1);
  expect(await evidence()).not.toHaveLength(0);
  await userEvent.click(screen.getByRole('button', { name: 'back' }));
  expect(where()).toBe('/compare');
});

it('what a plan link chose is said while it stays chosen: back from a course still, not once another plan is chosen', async () => {
  world(policies);
  page(planLink());
  await waitFor(() =>
    expect(linkNotice()).toHaveTextContent(PLAN_LINK_NOTICES.ready),
  );
  await userEvent.click(screen.getByRole('button', { name: '查看 CS 5010' }));
  await userEvent.click(screen.getByRole('button', { name: 'back' }));
  expect(await opened()).toHaveTextContent(STANDARD_PLAN);
  expect(linkNotice()).toHaveTextContent(PLAN_LINK_NOTICES.ready);
  await choose(PLAN, ALIGN_PLAN);
  expect(linkNotice()).toHaveTextContent('');
  await choose(PLAN, STANDARD_PLAN);
  expect(linkNotice()).toHaveTextContent('');
});

it.each([
  ['刷新方案及政策证据', null],
  ['刷新页面内容', 10 * 60_000],
])(
  'a plan link checked while %s reads the program again is settled by that read',
  async (button, cachedAgo) => {
    const first = held();
    let hold: ReturnType<typeof held> | null = first;
    let reads = 0;
    world((call) => {
      if (call.method !== 'GET' || call.path !== CURRICULUM)
        return policies(call);
      reads += 1;
      const read = hold;
      hold = null;
      return read?.response;
    });
    const client = seededQueryClient();
    // The sidebar's button cancels a read on its way over an answer in the cache: here one older than five minutes,
    // read again when the page opens, in which the shared plan was at another version.
    if (cachedAgo !== null)
      client.setQueryData(
        curriculumQuery(CS).queryKey,
        csBody({ ...revisions, [STANDARD]: 'e'.repeat(64) }),
        { updatedAt: Date.now() - cachedAgo },
      );
    page(planLink(), client);
    await waitFor(() => expect(linkNotice()).toHaveTextContent(CHECKING_LINK));
    const second = held();
    hold = second;
    await userEvent.click(screen.getAllByRole('button', { name: button })[0]!);
    // The read the link waited for was cancelled; answered late, it is dropped. Until the read in its place is in,
    // the link is still being checked: not settled from the answer in the cache.
    first.answer(json(csBody()));
    await moment();
    expect(linkNotice()).toHaveTextContent(CHECKING_LINK);
    second.answer(json(csBody()));
    await waitFor(() =>
      expect(linkNotice()).toHaveTextContent(PLAN_LINK_NOTICES.ready),
    );
    expect(combobox(PLAN)).toHaveTextContent(STANDARD_PLAN);
    expect(reads).toBe(2);
  },
);

// Another reader of the program (the search page with the same program chosen) keeps its read going after the
// program page stops reading it, so the read is answered instead of cancelled.
const otherReader = (client: QueryClient) =>
  new QueryObserver(client, {
    ...curriculumQuery(CS),
    enabled: false,
  }).subscribe(() => {});

it.each([
  ['cancelled', false],
  ['kept going by another reader', true],
])(
  'Back to another program while a plan link is checked (the read %s) stays there, and coming back the link is checked again',
  async (_name, kept) => {
    const later = held();
    let reads = 0;
    world((call) =>
      call.method === 'GET' && call.path === CURRICULUM && ++reads === 1
        ? later.response
        : policies(call),
    );
    const client = seededQueryClient();
    if (kept) otherReader(client);
    page(['/programs/ds-ms', planLink()], client);
    await waitFor(() => expect(linkNotice()).toHaveTextContent(CHECKING_LINK));
    await userEvent.click(screen.getByRole('button', { name: 'back' }));
    await waitFor(() => expect(where()).toBe('/programs/ds-ms'));
    later.answer(json(csBody()));
    await moment();
    expect(where()).toBe('/programs/ds-ms');
    expect(linkNotice()).toHaveTextContent('');
    await userEvent.click(screen.getByRole('button', { name: 'forward' }));
    await waitFor(() =>
      expect(linkNotice()).toHaveTextContent(PLAN_LINK_NOTICES.ready),
    );
    expect(where()).toBe('/programs/cs-ms');
    expect(combobox(PLAN)).toHaveTextContent(STANDARD_PLAN);
  },
);

it.each([
  ['the comparison page', '/compare', () => json(csBody()), false],
  [
    'the comparison page, the read refused',
    '/compare',
    () => apiError(422, 'validation_error', 'Bad request'),
    false,
  ],
  ['the landing', '/', () => json(csBody()), false],
  [
    'the comparison page, the read kept going by another reader',
    '/compare',
    () => json(csBody()),
    true,
  ],
  [
    'the comparison page, the read kept going and refused',
    '/compare',
    () => apiError(422, 'validation_error', 'Bad request'),
    true,
  ],
])(
  'Back to %s while a plan link is checked stays there',
  async (_name, before, answer, kept) => {
    const later = held();
    world((call) =>
      call.method === 'GET' && call.path === CURRICULUM
        ? later.response
        : undefined,
    );
    const client = seededQueryClient();
    if (kept) otherReader(client);
    page([before, planLink()], client);
    await waitFor(() => expect(where()).toBe('/programs/cs-ms'));
    await userEvent.click(screen.getByRole('button', { name: 'back' }));
    await waitFor(() => expect(where()).toBe(before));
    later.answer(answer());
    await moment();
    expect(where()).toBe(before);
  },
);

it('a plan link whose program cannot be read as it is says the plans cannot be had', async () => {
  world((call) =>
    call.path === CURRICULUM
      ? apiError(422, 'validation_error', 'Bad request')
      : undefined,
  );
  page(planLink());
  await waitFor(() =>
    expect(linkNotice()).toHaveTextContent(PLAN_LINK_NOTICES.unavailable),
  );
});

it('a draft plan at another version is stale, the version checked first as in Streamlit', async () => {
  world();
  page(
    planLink({
      plan: BRIDGE,
      pathway: 'bridge',
      plan_revision: 'f'.repeat(64),
    }),
  );
  await waitFor(() =>
    expect(linkNotice()).toHaveTextContent(PLAN_LINK_NOTICES.stale),
  );
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

// The course draft under a checked plan (R4b's PlanDraft, its answers from the API's check).
const BRIDGE_PLAN =
  'boston · Catalog 2026-2027 · Bridge · 共同部分／未限定 concentration';
const count = (n: number) => `已填 ${n}/20 门（不区分已修与打算修）`;
const codes = () => screen.getByRole('textbox', { name: /^课号/ });
const isDraft = (call: Call) =>
  call.method === 'POST' && call.path.endsWith('/draft');
const draftRegion = () =>
  screen.queryByRole('region', { name: '我的选课草案（只在本次会话）' });
const sentBodies = (calls: readonly Call[]) =>
  draftChecks(calls).map((check) => check.body as DraftRequest);
const nothingYet = (plan = STANDARD): DraftRequest => ({
  plan_content_sha256: revisions[plan]!,
  course_ids: [],
});
const moment = () =>
  act(() => new Promise<void>((resolve) => setTimeout(resolve, 20)));
async function add(text: string) {
  await userEvent.type(codes(), text);
  await userEvent.click(screen.getByRole('button', { name: '加入草案' }));
}
// cs-ms with its standard plan chosen, and the draft's first check answered.
async function standardChosen() {
  await opened();
  await choose(PLAN, STANDARD_PLAN);
  await screen.findByText(count(0));
}

it('choosing a checked plan checks its empty draft once, so the count and the rules are there from the start', async () => {
  const api = world(policies);
  page('/programs/cs-ms');
  await standardChosen();
  expect(draftChecks(api.calls)).toEqual([
    { plan: STANDARD, body: nothingYet() },
  ]);
  expect(document.querySelector('[data-kind="tree"]')).not.toBeNull();
});

it('adding sends the draft and the words typed, removing sends the rest, and each answer is the draft from then on', async () => {
  const api = world(policies);
  page('/programs/cs-ms');
  await standardChosen();
  await add('CS 5010, CS 5800');
  expect(await screen.findByText(count(2))).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: '移除 CS 5010' }));
  expect(await screen.findByText(count(1))).toBeInTheDocument();
  expect(sentBodies(api.calls)).toEqual([
    nothingYet(),
    { ...nothingYet(), input: 'CS 5010, CS 5800' },
    { ...nothingYet(), course_ids: ['c-cs-5800'] },
  ]);
});

it('a course in the draft opens its page with its ID, and on the way back the draft is there, not checked again', async () => {
  const api = world(policies);
  page('/programs/cs-ms');
  await standardChosen();
  await add('CS 5010, CS 5800');
  await screen.findByText(count(2));
  await userEvent.click(
    screen.getByRole('button', { name: 'CS 5010 · 课程页／年度先修' }),
  );
  expect(where()).toBe('/course/CS-5010');
  expect(stateOf()).toEqual({ courseId: 'c-cs-5010' });
  await userEvent.click(screen.getByRole('button', { name: 'back' }));
  expect(await screen.findByText(count(2))).toBeInTheDocument();
  expect(draftChecks(api.calls)).toHaveLength(2);
});

it('the last check counts: one answered after it is dropped', async () => {
  const late = held();
  const api = world((call) =>
    isDraft(call) &&
    (call.body as DraftRequest).course_ids.join() === 'c-cs-5800'
      ? late.response
      : policies(call),
  );
  page('/programs/cs-ms');
  await standardChosen();
  await add('CS 5010, CS 5800');
  await screen.findByText(count(2));
  await userEvent.click(screen.getByRole('button', { name: '移除 CS 5010' }));
  expect(await screen.findByText('正在核对课程…')).toBeInTheDocument();
  // The answer before stays while the check is on its way, and its buttons work.
  await userEvent.click(screen.getByRole('button', { name: '移除 CS 5800' }));
  expect(await screen.findByText(count(0))).toBeInTheDocument();
  late.answer(
    json(draftAnswer(STANDARD, { ...nothingYet(), course_ids: ['c-cs-5800'] })),
  );
  await moment();
  expect(screen.getByText(count(0))).toBeInTheDocument();
  expect(sentBodies(api.calls).map((body) => body.course_ids)).toEqual([
    [],
    [],
    ['c-cs-5800'],
    [],
  ]);
  // The check it took the place of was stopped on its way.
  expect(api.calls.filter(isDraft)[2]!.init.signal?.aborted).toBe(true);
});

it('under another plan the answer before goes at once, and the same courses are checked there', async () => {
  const align = held();
  const api = world((call) =>
    isDraft(call) && call.path.includes(ALIGN)
      ? align.response
      : policies(call),
  );
  page('/programs/cs-ms');
  await standardChosen();
  await add('CS 5010, CS 5800');
  await screen.findByText(count(2));
  await choose(PLAN, ALIGN_PLAN);
  expect(await screen.findByText('正在核对课程…')).toBeInTheDocument();
  expect(screen.queryByText(count(2))).not.toBeInTheDocument();
  // Kept, the answer before would be drawn as one for another content version, without its count.
  expect(screen.queryByText(/内容版本不一致/)).not.toBeInTheDocument();
  const last = draftChecks(api.calls).at(-1)!;
  expect(last).toEqual({
    plan: ALIGN,
    body: {
      plan_content_sha256: revisions[ALIGN],
      course_ids: ['c-cs-5010', 'c-cs-5800'],
    },
  });
  align.answer(json(draftAnswer(ALIGN, last.body as DraftRequest)));
  expect(await screen.findByText(count(2))).toBeInTheDocument();
});

it('清空草案 takes the draft and its answer at once, then checks the empty draft', async () => {
  const later = held();
  let clearing = false;
  const api = world((call) =>
    isDraft(call) && clearing ? later.response : policies(call),
  );
  page('/programs/cs-ms');
  await standardChosen();
  await add('CS 5010, CS 5800');
  await screen.findByText(count(2));
  clearing = true;
  await userEvent.click(screen.getByRole('button', { name: '清空草案' }));
  expect(screen.queryByText(count(2))).not.toBeInTheDocument();
  expect(screen.getByText('正在核对课程…')).toBeInTheDocument();
  expect(sentBodies(api.calls)).toHaveLength(3);
  expect(sentBodies(api.calls).at(-1)).toEqual(nothingYet());
  later.answer(json(draftAnswer(STANDARD, nothingYet())));
  expect(await screen.findByText(count(0))).toBeInTheDocument();
});

it('a check that failed for a moment is sent again by 重新核对', async () => {
  let failing = false;
  const api = world((call) =>
    isDraft(call) && failing ? down() : policies(call),
  );
  page('/programs/cs-ms');
  await standardChosen();
  failing = true;
  await add('CS 5010, CS 5800');
  expect(await screen.findByText(/^无法核对草案。/)).toBeInTheDocument();
  failing = false;
  await userEvent.click(screen.getByRole('button', { name: '重新核对' }));
  expect(await screen.findByText(count(2))).toBeInTheDocument();
  const [, failed, again] = sentBodies(api.calls);
  expect(failed).toEqual({ ...nothingYet(), input: 'CS 5010, CS 5800' });
  expect(again).toEqual(failed);
});

it('a plan the check finds stale goes, focus goes to the plan selector, and plans read again that changed say so', async () => {
  let refused = false;
  const api = world((call) => {
    if (isDraft(call) && refused) return json(stale.body, 409);
    if (call.path === CURRICULUM && refused)
      return json(csBody({ ...revisions, [STANDARD]: 'f'.repeat(64) }));
    return policies(call);
  });
  page('/programs/cs-ms');
  await standardChosen();
  refused = true;
  // Focus is on 加入草案, inside the draft that goes.
  await add('CS 5010');
  await waitFor(() => expect(combobox(PLAN)).toHaveFocus());
  expect(combobox(PLAN)).toHaveTextContent(PLAN_PLACEHOLDER);
  expect(draftRegion()).toBeNull();
  expect(await screen.findAllByText(PLAN_REVISED_LINE)).toHaveLength(2);
  expect(screen.queryByText(PLAN_REFUSED_LINE)).not.toBeInTheDocument();
  expect(api.count('GET', CURRICULUM)).toBe(2);
});

it('a plan the check refuses in plans that did not change goes, the page says why in R4b’s words, and the draft keeps its courses', async () => {
  let refused = false;
  const api = world((call) =>
    isDraft(call) && refused ? json(unusable.body, 409) : policies(call),
  );
  page('/programs/cs-ms');
  await standardChosen();
  await add('CS 5010, CS 5800');
  await screen.findByText(count(2));
  refused = true;
  await userEvent.clear(codes());
  await add('CS 6140');
  await waitFor(() =>
    expect(screen.getByRole('status', { name: '方案更新' })).toHaveTextContent(
      PLAN_REFUSED_LINE,
    ),
  );
  // R4b's sentence is nowhere else on the page, so it is shown, not only heard.
  expect(screen.getByText(PLAN_REFUSED_LINE).closest('.visually-hidden')).toBe(
    null,
  );
  expect(combobox(PLAN)).toHaveTextContent(PLAN_PLACEHOLDER);
  expect(screen.queryByText(PLAN_REVISED_LINE)).not.toBeInTheDocument();
  expect(api.count('GET', CURRICULUM)).toBe(2);
  refused = false;
  await choose(PLAN, ALIGN_PLAN);
  expect(await screen.findByText(count(2))).toBeInTheDocument();
  expect(draftChecks(api.calls).at(-1)).toEqual({
    plan: ALIGN,
    body: {
      plan_content_sha256: revisions[ALIGN],
      course_ids: ['c-cs-5010', 'c-cs-5800'],
    },
  });
  expect(screen.queryByText(PLAN_REFUSED_LINE)).not.toBeInTheDocument();
});

it('a plan list that changed while focus was in the plan’s block hands focus to the plan selector', async () => {
  let changed = false;
  world((call) =>
    call.path === CURRICULUM && changed
      ? json(csBody({ ...revisions, [STANDARD]: 'f'.repeat(64) }))
      : policies(call),
  );
  const { client } = page('/programs/cs-ms');
  await standardChosen();
  // In the block of the plan, which goes with the draft, not in the draft.
  act(() => screen.getByRole('link', { name: '官方目录来源' }).focus());
  changed = true;
  await act(() =>
    client.invalidateQueries({
      queryKey: curriculumQuery(CS).queryKey,
      exact: true,
    }),
  );
  await waitFor(() => expect(draftRegion()).toBeNull());
  expect(combobox(PLAN)).toHaveFocus();
});

it('a plan list that changed while nothing had focus gives focus to nothing, the plan selector included', async () => {
  let changed = false;
  world((call) =>
    call.path === CURRICULUM && changed
      ? json(csBody({ ...revisions, [STANDARD]: 'f'.repeat(64) }))
      : policies(call),
  );
  const { client } = page('/programs/cs-ms');
  await standardChosen();
  act(() => (document.activeElement as HTMLElement).blur());
  expect(document.activeElement).toBe(document.body);
  changed = true;
  await act(() =>
    client.invalidateQueries({
      queryKey: curriculumQuery(CS).queryKey,
      exact: true,
    }),
  );
  await waitFor(() => expect(draftRegion()).toBeNull());
  expect(document.activeElement).toBe(document.body);
});

// The draft goes with focus elsewhere, so this is about the page not taking the focus the account box gives on.
it('a keyboard logout with the draft open leaves focus where the account box puts it, on its login button', async () => {
  const logout = held();
  world((call) =>
    call.path === '/auth/logout' ? logout.response : policies(call),
  );
  page('/programs/cs-ms', seededQueryClient({ viewer: member }));
  await standardChosen();
  screen.getAllByRole('button', { name: '退出登录' })[0]!.focus();
  await userEvent.keyboard('{Enter}');
  await waitFor(() =>
    expect(
      screen.getAllByRole('button', { name: '正在退出…' })[0],
    ).toBeDisabled(),
  );
  // A browser moves focus off the disabled button to the page; jsdom does not (session.test.tsx).
  document.body.tabIndex = -1;
  document.body.focus();
  document.body.removeAttribute('tabindex');
  logout.answer(new Response(null, { status: 204 }));
  await waitFor(() => expect(draftRegion()).toBeNull());
  expect(
    screen.getAllByRole('button', { name: '用 NEU 邮箱登录' })[0],
  ).toHaveFocus();
});

it('the sentence for a refused plan is R4b’s for each of the four reasons', () => {
  for (const reason of ['missing', 'stale', 'draft', 'unusable'])
    expect(draftFailureMessage(new ApiError(409, { reason }))).toBe(
      PLAN_REFUSED_LINE,
    );
});

it('a plan that cannot be checked for now keeps the choice, and the draft offers 重新核对', async () => {
  let refused = false;
  world((call) =>
    isDraft(call) && refused ? json(unavailable.body, 409) : policies(call),
  );
  page('/programs/cs-ms');
  await standardChosen();
  refused = true;
  await add('CS 5010');
  expect(
    await screen.findByText(
      '暂时无法核对所选方案，草案没有计算；请稍后重新核对。',
    ),
  ).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '重新核对' })).toBeInTheDocument();
  expect(combobox(PLAN)).toHaveTextContent(STANDARD_PLAN);
});

it('a logout empties the draft and what was typed', async () => {
  const api = world((call) =>
    call.path === '/auth/logout'
      ? new Response(null, { status: 204 })
      : policies(call),
  );
  page('/programs/cs-ms', seededQueryClient({ viewer: member }));
  await standardChosen();
  await add('CS 5010, CS 5800');
  await screen.findByText(count(2));
  await userEvent.click(
    screen.getAllByRole('button', { name: '退出登录' })[0]!,
  );
  await waitFor(() =>
    expect(combobox(PLAN)).toHaveTextContent(PLAN_PLACEHOLDER),
  );
  await choose(PLAN, STANDARD_PLAN);
  expect(await screen.findByText(count(0))).toBeInTheDocument();
  expect(codes()).toHaveValue('');
  expect(sentBodies(api.calls).at(-1)).toEqual(nothingYet());
});

it.each([
  ['not checked against its sources', BRIDGE_PLAN, csBody()],
  [
    'whose content version the page does not know',
    STANDARD_PLAN,
    csBody(
      Object.fromEntries(
        Object.entries(revisions).filter(([id]) => id !== STANDARD),
      ),
    ),
  ],
])(
  'a plan %s has no draft, and no check is asked for',
  async (_name, label, answer) => {
    const api = world((call) =>
      call.path === CURRICULUM ? json(answer) : policies(call),
    );
    page('/programs/cs-ms');
    await opened();
    await choose(PLAN, label);
    await moment();
    expect(draftRegion()).toBeNull();
    expect(draftChecks(api.calls)).toEqual([]);
  },
);

// React gives focus back after an update to the element that had it before, so where focus ends up shows nothing; a
// moment of focus on the plan selector or the curriculum would still blur the button, so that is watched too.
it('after 刷新方案及政策证据 the draft is checked again under the plan chosen again; focus stays on the button, not even for a moment elsewhere', async () => {
  const api = world(policies);
  page('/programs/cs-ms');
  await standardChosen();
  const refresh = screen.getByRole('button', { name: '刷新方案及政策证据' });
  const refreshBlurred = vi.fn();
  refresh.addEventListener('blur', refreshBlurred);
  await userEvent.click(refresh);
  // The draft went with the choice, but focus was not in it.
  expect(draftRegion()).toBeNull();
  expect(refresh).toHaveFocus();
  expect(refreshBlurred).not.toHaveBeenCalled();
  await waitFor(() => expect(api.count('GET', CURRICULUM)).toBe(2));
  expect(refresh).toHaveFocus();
  expect(await opened()).toHaveTextContent(PLAN_PLACEHOLDER);
  await choose(PLAN, STANDARD_PLAN);
  expect(await screen.findByText(count(0))).toBeInTheDocument();
  expect(draftChecks(api.calls)).toHaveLength(2);
});

it.each([
  ['unusable', unusable.body],
  ['stale in plans that did not change', stale.body],
])(
  'a plan refused as %s and chosen again is checked again, its draft’s courses with it',
  async (_name, refusal) => {
    let refused = false;
    const api = world((call) =>
      isDraft(call) && refused ? json(refusal, 409) : policies(call),
    );
    page('/programs/cs-ms');
    await standardChosen();
    await add('CS 5010, CS 5800');
    await screen.findByText(count(2));
    refused = true;
    await userEvent.clear(codes());
    await add('CS 6140');
    await waitFor(() =>
      expect(
        screen.getByRole('status', { name: '方案更新' }),
      ).toHaveTextContent(PLAN_REFUSED_LINE),
    );
    refused = false;
    await choose(PLAN, STANDARD_PLAN);
    expect(await screen.findByText(count(2))).toBeInTheDocument();
    expect(draftChecks(api.calls)).toHaveLength(4);
    expect(sentBodies(api.calls).at(-1)).toEqual({
      ...nothingYet(),
      course_ids: ['c-cs-5010', 'c-cs-5800'],
    });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.queryByText(PLAN_REFUSED_LINE)).not.toBeInTheDocument();
  },
);

it.each([
  ['a plan with no draft', BRIDGE_PLAN],
  ['no plan', PLAN_PLACEHOLDER],
])(
  'the check on its way stops when %s is chosen, and its refusal, answered late, says nothing',
  async (_name, next) => {
    const late = held();
    let holding = false;
    const api = world((call) =>
      isDraft(call) && holding ? late.response : policies(call),
    );
    page('/programs/cs-ms');
    await standardChosen();
    holding = true;
    await add('CS 5010');
    await screen.findByText('正在核对课程…');
    await choose(PLAN, next);
    expect(api.calls.filter(isDraft).at(-1)!.init.signal?.aborted).toBe(true);
    late.answer(json(unusable.body, 409));
    await moment();
    expect(combobox(PLAN)).toHaveTextContent(next);
    expect(screen.getByRole('status', { name: '方案更新' })).toHaveTextContent(
      '',
    );
    expect(api.count('GET', CURRICULUM)).toBe(1);
  },
);

// The plans are read again after the hand-off, as over a network: the selector goes a commit later.
it.each([
  ['no plan left to offer', () => json({ ...csBody({}), plans: [] })],
  ['the program gone', () => apiError(404, 'not_found', 'Program not found')],
])(
  'focus handed to the plan selector goes to the curriculum when the plans read again leave %s',
  async (_name, reread) => {
    let refused = false;
    const read = held();
    world((call) => {
      if (isDraft(call) && refused)
        return json({ ...stale.body, reason: 'missing' }, 409);
      if (call.path === CURRICULUM && refused) return read.response;
      return policies(call);
    });
    page('/programs/cs-ms');
    await standardChosen();
    refused = true;
    await add('CS 5010');
    await waitFor(() => expect(combobox(PLAN)).toHaveFocus());
    read.answer(reread());
    await waitFor(() => expect(combobox(PLAN)).toBeNull());
    expect(screen.getByRole('region', { name: '项目课程表' })).toHaveFocus();
  },
);

it('focus in the plan’s block when the selector goes too goes to the curriculum, without scrolling', async () => {
  const later = held();
  let holding = false;
  world((call) =>
    call.path === CURRICULUM && holding ? later.response : policies(call),
  );
  page('/programs/cs-ms');
  await standardChosen();
  act(() => screen.getByRole('link', { name: '官方目录来源' }).focus());
  holding = true;
  const focus = vi.spyOn(HTMLElement.prototype, 'focus');
  // Pressed by a script, so focus stays in the block: 刷新 takes the selector with the curriculum.
  act(() => screen.getByRole('button', { name: '刷新方案及政策证据' }).click());
  await waitFor(() => expect(combobox(PLAN)).toBeNull());
  const curriculum = screen.getByRole('region', { name: '项目课程表' });
  expect(curriculum).toHaveFocus();
  expect(focus.mock.calls[focus.mock.contexts.indexOf(curriculum)]).toEqual([
    { preventScroll: true },
  ]);
});

it('focus handed to the plan selector does not scroll', async () => {
  let refused = false;
  world((call) =>
    isDraft(call) && refused ? json(unusable.body, 409) : policies(call),
  );
  page('/programs/cs-ms');
  await standardChosen();
  refused = true;
  const focus = vi.spyOn(HTMLElement.prototype, 'focus');
  await add('CS 5010');
  await waitFor(() => expect(combobox(PLAN)).toHaveFocus());
  const selector = combobox(PLAN)!;
  expect(focus.mock.calls[focus.mock.contexts.indexOf(selector)]).toEqual([
    { preventScroll: true },
  ]);
});

it('policy evidence that cannot be read says so, not loading for ever', async () => {
  world((call) => (call.path === POLICIES ? down() : undefined));
  page('/programs/cs-ms');
  await opened();
  await choose(PLAN, STANDARD_PLAN);
  expect(
    await screen.findByText(/^无法加载所选方案的政策证据/),
  ).toBeInTheDocument();
  expect(screen.queryByText('正在加载政策证据…')).not.toBeInTheDocument();
});

it('a logout takes what the page said about the plans too', async () => {
  let changed = false;
  world((call) => {
    if (call.path === '/auth/logout')
      return new Response(null, { status: 204 });
    if (call.path === CURRICULUM && changed)
      return json(csBody({ ...revisions, [STANDARD]: 'f'.repeat(64) }));
    return policies(call);
  });
  const { client } = page(
    '/programs/cs-ms',
    seededQueryClient({ viewer: member }),
  );
  await opened();
  await choose(PLAN, STANDARD_PLAN);
  changed = true;
  await act(() =>
    client.invalidateQueries({
      queryKey: curriculumQuery(CS).queryKey,
      exact: true,
    }),
  );
  expect(await screen.findAllByText(PLAN_REVISED_LINE)).toHaveLength(2);
  await userEvent.click(
    screen.getAllByRole('button', { name: '退出登录' })[0]!,
  );
  await waitFor(() =>
    expect(screen.queryAllByText(PLAN_REVISED_LINE)).toHaveLength(0),
  );
});

it('刷新方案及政策证据 while the plans are read again after a refusal leaves nothing to say after', async () => {
  const reread = held();
  let refused = false;
  let reads = 0;
  world((call) => {
    if (isDraft(call) && refused) return json(unusable.body, 409);
    if (
      call.method === 'GET' &&
      call.path === CURRICULUM &&
      refused &&
      ++reads === 1
    )
      return reread.response;
    return policies(call);
  });
  page('/programs/cs-ms');
  await standardChosen();
  refused = true;
  await add('CS 5010');
  await waitFor(() =>
    expect(combobox(PLAN)).toHaveTextContent(PLAN_PLACEHOLDER),
  );
  await userEvent.click(
    screen.getByRole('button', { name: '刷新方案及政策证据' }),
  );
  reread.answer(json(csBody()));
  await moment();
  expect(screen.queryByText(PLAN_REFUSED_LINE)).not.toBeInTheDocument();
});

it('刷新方案及政策证据 stops the draft check on its way', async () => {
  const later = held();
  let holding = false;
  const api = world((call) =>
    isDraft(call) && holding ? later.response : policies(call),
  );
  page('/programs/cs-ms');
  await standardChosen();
  holding = true;
  await add('CS 5010');
  await screen.findByText('正在核对课程…');
  await userEvent.click(
    screen.getByRole('button', { name: '刷新方案及政策证据' }),
  );
  expect(api.calls.filter(isDraft).at(-1)!.init.signal?.aborted).toBe(true);
});

it('the same plan chosen again from the plans read after a stale refusal is checked at its new version', async () => {
  let refused = false;
  const api = world((call) => {
    if (
      isDraft(call) &&
      refused &&
      (call.body as DraftRequest).plan_content_sha256 === revisions[STANDARD]
    )
      return json(stale.body, 409);
    if (call.path === CURRICULUM && refused)
      return json(csBody({ ...revisions, [STANDARD]: 'f'.repeat(64) }));
    return policies(call);
  });
  page('/programs/cs-ms');
  await standardChosen();
  refused = true;
  await add('CS 5010');
  expect(await screen.findAllByText(PLAN_REVISED_LINE)).toHaveLength(2);
  await choose(PLAN, STANDARD_PLAN);
  await waitFor(() =>
    expect(sentBodies(api.calls).at(-1)!.plan_content_sha256).toBe(
      'f'.repeat(64),
    ),
  );
});

// What the draft shows comes from the wiring (R4b spec section 3): the last answer, and the last failure until an
// answer.
it('a failed check keeps the answer before it in view, and a retry that is answered takes the failure away', async () => {
  let failing = false;
  world((call) => (isDraft(call) && failing ? down() : policies(call)));
  page('/programs/cs-ms');
  await standardChosen();
  await add('CS 5010, CS 5800');
  await screen.findByText(count(2));
  failing = true;
  await userEvent.click(screen.getByRole('button', { name: '移除 CS 5010' }));
  expect(await screen.findByText(/^无法核对草案。/)).toBeInTheDocument();
  expect(screen.getByText(count(2))).toBeInTheDocument();
  failing = false;
  await userEvent.click(screen.getByRole('button', { name: '重新核对' }));
  expect(await screen.findByText(count(1))).toBeInTheDocument();
  expect(screen.queryByText(/^无法核对草案。/)).not.toBeInTheDocument();
});

it('while a retry is on its way the failure and its button stay', async () => {
  const later = held();
  let mode: 'answer' | 'down' | 'hold' = 'answer';
  world((call) => {
    if (!isDraft(call) || mode === 'answer') return policies(call);
    return mode === 'down' ? down() : later.response;
  });
  page('/programs/cs-ms');
  await standardChosen();
  mode = 'down';
  await add('CS 5010');
  expect(await screen.findByText(/^无法核对草案。/)).toBeInTheDocument();
  mode = 'hold';
  await userEvent.click(screen.getByRole('button', { name: '重新核对' }));
  expect(await screen.findByText('正在核对课程…')).toBeInTheDocument();
  expect(screen.getByText(/^无法核对草案。/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '重新核对' })).toBeInTheDocument();
});

it('a program’s page further down the address is no page', () => {
  world();
  page('/programs/cs-ms/plans');
  expect(document.title).toBe('找不到页面 · NEU-Compass');
});
