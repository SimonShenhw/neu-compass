import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it } from 'vitest';
import { axe } from 'vitest-axe';
import { configQuery, createQueryClient, meQuery } from '../api/queries';
import type { Member } from '../api/queries';
import guest from '../fixtures/coop/list-guest.json';
import member0 from '../fixtures/coop/list-member-0.json';
import member2 from '../fixtures/coop/list-member-2.json';
import pending from '../fixtures/coop/upload-pending.json';
import { FALLBACK_NOTICE } from '../layout/AppShell';
import {
  apiError,
  asked,
  fakeApi,
  held,
  json,
  livePage,
} from '../test/fakeApi';
import { seededQueryClient } from '../test/withApi';

const member = (count: number, userId = 'u-1'): Member => ({
  kind: 'member',
  userId,
  email: 'synthetic.student@husky.neu.edu',
  displayName: 'Synthetic Student',
  contributionCount: count,
});
const identity = (count: number) => ({
  user_id: 'u-1',
  email: 'synthetic.student@husky.neu.edu',
  display_name: 'Synthetic Student',
  contribution_count: count,
});
// The desktop sidebar (a page may have an aside of its own, as Co-op's does).
const sidebar = () =>
  screen.getByRole('navigation', { name: '主导航' }).closest('aside')!;
const form = () => screen.getByRole('form', { name: '分享你的 Co-op 经验' });
const fallback = () => screen.getByRole('status', { name: '内容更新' });
async function fillRequired() {
  await userEvent.type(screen.getByLabelText(/^公司/), '  Example Co.  ');
  await userEvent.type(screen.getByLabelText(/^职位/), 'Data Co-op');
}
const submit = () =>
  userEvent.click(screen.getByRole('button', { name: '提交经验' }));

it('a guest sees what the API gives a guest, asked once with the cookie, and no upload form', async () => {
  const api = fakeApi(({ path }) =>
    path === '/coop' ? json(guest.body) : json(null, 404),
  );
  livePage('/coop');
  expect(await screen.findAllByRole('article')).toHaveLength(4);
  expect(api.calls).toHaveLength(1);
  expect(api.calls[0]).toMatchObject({
    method: 'GET',
    path: '/coop',
    search: '',
    init: { credentials: 'include' },
  });
  expect(screen.getByRole('region', { name: '查看权限' })).toHaveTextContent(
    '你现在是游客',
  );
  expect(
    screen.queryByRole('form', { name: '分享你的 Co-op 经验' }),
  ).not.toBeInTheDocument();
  // The page says who is looking itself, so the top bar has no guest badge.
  expect(
    screen.getByRole('heading', { level: 1 }).closest('header'),
  ).not.toHaveTextContent('游客');
});

it('a member’s list is kept under who they are and their count, and goes at logout with their draft', async () => {
  const user = userEvent.setup();
  let lists = 0;
  const api = fakeApi(({ method, path }) => {
    if (method === 'POST' && path === '/auth/logout')
      return new Response(null, { status: 204 });
    if (path === '/coop') return json(lists++ ? guest.body : member2.body);
    return json(null, 404);
  });
  const client = livePage('/coop', seededQueryClient({ viewer: member(2) }));
  expect(await screen.findByText('$40-45/hr')).toBeInTheDocument();
  expect(client.getQueryData(['viewer', 'member:u-1:2', 'coop'])).toHaveLength(
    4,
  );
  await user.type(screen.getByLabelText(/^公司/), '私有合成草稿');
  await user.click(within(sidebar()).getByRole('button', { name: '退出登录' }));
  await waitFor(() =>
    expect(screen.getByRole('region', { name: '查看权限' })).toHaveTextContent(
      '你现在是游客',
    ),
  );
  expect(
    client.getQueryData(['viewer', 'member:u-1:2', 'coop']),
  ).toBeUndefined();
  await waitFor(() => expect(api.count('GET', '/coop')).toBe(2));
  expect(await screen.findAllByRole('article')).toHaveLength(4);
  expect(screen.queryByText('$40-45/hr')).not.toBeInTheDocument();
  expect(screen.queryByDisplayValue('私有合成草稿')).not.toBeInTheDocument();
});

it('nothing is asked before /auth/me says who is looking', async () => {
  const me = held();
  const api = fakeApi(({ path }) =>
    path === '/auth/me'
      ? me.response
      : path === '/coop'
        ? json(member0.body)
        : json(null, 404),
  );
  const client = createQueryClient();
  client.setQueryData(configQuery.queryKey, {
    answer_feedback_enabled: false,
    login_available: true,
  });
  livePage('/coop', client);
  expect(screen.getByRole('status', { name: 'Co-op 加载' })).toHaveTextContent(
    '正在加载',
  );
  await waitFor(() => expect(api.count('GET', '/auth/me')).toBe(1));
  expect(api.count('GET', '/coop')).toBe(0);
  me.answer(json(identity(0)));
  expect(
    await screen.findByText('已公开贡献：0 条 · 当前等级 0'),
  ).toBeInTheDocument();
  expect(api.count('GET', '/coop')).toBe(1);
  expect(client.getQueryData(['viewer', 'member:u-1:0', 'coop'])).toHaveLength(
    4,
  );
});

it('when /auth/me fails for a moment the list is still asked for, as unsure, and the page reads as a guest’s, details too', async () => {
  // The API answers by the cookie, which here unlocks everything (A27).
  const api = fakeApi(({ path }) =>
    path === '/auth/me'
      ? apiError(503, 'service_unavailable', 'down')
      : path === '/coop'
        ? json(member2.body)
        : json(null, 404),
  );
  const client = createQueryClient();
  client.setQueryData(configQuery.queryKey, {
    answer_feedback_enabled: false,
    login_available: true,
  });
  livePage('/coop', client);
  expect(await screen.findAllByRole('article')).toHaveLength(4);
  expect(api.count('GET', '/coop')).toBe(1);
  expect(client.getQueryData(['viewer', 'unsure', 'coop'])).toHaveLength(4);
  expect(screen.getByRole('region', { name: '查看权限' })).toHaveTextContent(
    '你现在是游客',
  );
  expect(screen.queryByText('$40-45/hr')).not.toBeInTheDocument();
  expect(screen.queryByText('面试经过')).not.toBeInTheDocument();
  expect(screen.queryByText('技术问题')).not.toBeInTheDocument();
  expect(
    screen.getAllByText('这条有薪资区间：你分享的经验有 2 条公开后解锁'),
  ).toHaveLength(2);
});

it('every visit asks again, and the last list shows at once meanwhile', async () => {
  const user = userEvent.setup();
  const second = held();
  let lists = 0;
  const api = fakeApi(({ path }) =>
    path === '/coop'
      ? lists++
        ? second.response
        : json(guest.body)
      : json(null, 404),
  );
  livePage('/coop');
  expect(await screen.findAllByRole('article')).toHaveLength(4);
  await user.click(within(sidebar()).getByRole('link', { name: /培养方案/ }));
  await user.click(within(sidebar()).getByRole('link', { name: /Co-op 经验/ }));
  expect(screen.getAllByRole('article')).toHaveLength(4);
  await waitFor(() => expect(api.count('GET', '/coop')).toBe(2));
  second.answer(json([guest.body[0]]));
  await waitFor(() => expect(screen.getAllByRole('article')).toHaveLength(1));
});

it('a temporary failure keeps the last list and says so above the page; a definite answer does not', async () => {
  const user = userEvent.setup();
  const answers = [
    () => json(guest.body),
    () => apiError(503, 'service_unavailable', 'down'),
    () => apiError(404, 'not_found', 'gone'),
  ];
  fakeApi(({ path }) =>
    path === '/coop' ? answers.shift()!() : json(null, 404),
  );
  livePage('/coop');
  expect(await screen.findAllByRole('article')).toHaveLength(4);
  expect(fallback()).toBeEmptyDOMElement();
  const refresh = within(sidebar()).getByRole('button', {
    name: '刷新页面内容',
  });
  await user.click(refresh);
  await waitFor(() => expect(fallback()).toHaveTextContent(FALLBACK_NOTICE));
  expect(screen.getAllByRole('article')).toHaveLength(4);
  await user.click(refresh);
  expect(
    await screen.findByText('Co-op 列表暂时加载不了，请稍后重试。'),
  ).toBeInTheDocument();
  expect(screen.queryAllByRole('article')).toHaveLength(0);
  expect(fallback()).toBeEmptyDOMElement();
});

it('a list with a row the page cannot read is not shown at all', async () => {
  fakeApi(({ path }) =>
    path === '/coop'
      ? json([...guest.body, { ...guest.body[0], visibility_level: 3 }])
      : json(null, 404),
  );
  livePage('/coop');
  expect(
    await screen.findByText('Co-op 列表暂时加载不了，请稍后重试。'),
  ).toBeInTheDocument();
  expect(screen.queryAllByRole('article')).toHaveLength(0);
});

it('重试 asks again', async () => {
  const user = userEvent.setup();
  const answers = [
    () => apiError(503, 'service_unavailable', 'down'),
    () => json(guest.body),
  ];
  const api = fakeApi(({ path }) =>
    path === '/coop' ? answers.shift()!() : json(null, 404),
  );
  livePage('/coop');
  await user.click(await screen.findByRole('button', { name: '重试' }));
  expect(await screen.findAllByRole('article')).toHaveLength(4);
  expect(api.count('GET', '/coop')).toBe(2);
});

it('while 重试 is on its way the list shows as loading, not as the failure', async () => {
  const user = userEvent.setup();
  const second = held();
  let lists = 0;
  fakeApi(({ path }) =>
    path === '/coop'
      ? lists++
        ? second.response
        : apiError(503, 'service_unavailable', 'down')
      : json(null, 404),
  );
  livePage('/coop');
  await user.click(await screen.findByRole('button', { name: '重试' }));
  await waitFor(() =>
    expect(
      screen.queryByText('Co-op 列表暂时加载不了，请稍后重试。'),
    ).not.toBeInTheDocument(),
  );
  expect(
    within(screen.getByRole('region', { name: 'Co-op 经历列表' })).getByRole(
      'status',
    ),
  ).toHaveTextContent('正在加载');
  second.answer(json(guest.body));
  expect(await screen.findAllByRole('article')).toHaveLength(4);
});

// After a success the failure stays on the query while it is asked again (only a query that never had data goes back
// to pending), so this is the path where the page itself has to tell a retry from the failure.
it('after a definite answer replaced the list, 重试 shows it as loading until its answer', async () => {
  const user = userEvent.setup();
  const third = held();
  const answers = [
    () => json(guest.body),
    () => apiError(404, 'not_found', 'gone'),
    () => third.response,
  ];
  fakeApi(({ path }) =>
    path === '/coop' ? answers.shift()!() : json(null, 404),
  );
  livePage('/coop');
  expect(await screen.findAllByRole('article')).toHaveLength(4);
  await user.click(
    within(sidebar()).getByRole('button', { name: '刷新页面内容' }),
  );
  await user.click(await screen.findByRole('button', { name: '重试' }));
  await waitFor(() =>
    expect(
      screen.queryByText('Co-op 列表暂时加载不了，请稍后重试。'),
    ).not.toBeInTheDocument(),
  );
  expect(
    within(screen.getByRole('region', { name: 'Co-op 经历列表' })).getByRole(
      'status',
    ),
  ).toHaveTextContent('正在加载');
  third.answer(json([guest.body[0]]));
  await waitFor(() => expect(screen.getAllByRole('article')).toHaveLength(1));
});

it('another person starts from a fresh page, while the same person keeps theirs', async () => {
  const user = userEvent.setup();
  fakeApi(({ path }) =>
    path === '/coop' ? json(member0.body) : json(null, 404),
  );
  const client = livePage('/coop', seededQueryClient({ viewer: member(0) }));
  await screen.findAllByRole('article');
  await user.type(screen.getByLabelText(/^公司/), '私有合成草稿');
  act(() => {
    client.setQueryData(meQuery.queryKey, member(1));
  });
  await screen.findByText('已公开贡献：1 条 · 当前等级 1');
  expect(screen.getByLabelText(/^公司/)).toHaveValue('私有合成草稿');
  act(() => {
    client.setQueryData(meQuery.queryKey, member(1, 'u-2'));
  });
  await waitFor(() => expect(screen.getByLabelText(/^公司/)).toHaveValue(''));
});

it('an upload sends the form exactly, as a write; a count the server did not change asks nothing more', async () => {
  const api = fakeApi(({ method, path }) =>
    method === 'POST' && path === '/coop'
      ? json(pending.body, 201)
      : path === '/coop'
        ? json(member0.body)
        : path === '/auth/me'
          ? json(identity(0))
          : json(null, 404),
  );
  livePage('/coop', seededQueryClient({ viewer: member(0) }));
  await screen.findAllByRole('article');
  await fillRequired();
  await submit();
  expect(
    await screen.findByRole('status', { name: '投稿结果' }),
  ).toHaveTextContent('已私有收集');
  expect(screen.getByText(pending.body.coop_id)).toBeInTheDocument();
  const upload = api.calls.find((call) => call.method === 'POST')!;
  expect(upload.body).toEqual({
    company: 'Example Co.',
    role: 'Data Co-op',
    coop_term: null,
    industry: null,
    duration_months: null,
    related_courses: [],
    interview_summary: null,
    technical_questions: null,
    salary_range_usd: null,
  });
  expect(upload.init).toMatchObject({
    credentials: 'include',
    headers: { 'X-NEU-Compass': '1', 'Content-Type': 'application/json' },
  });
  expect(api.count('POST', '/coop')).toBe(1);
  expect(api.count('GET', '/coop')).toBe(1);
  expect(sidebar()).toHaveTextContent('贡献数：0');
  // Who is signed in was asked again just before (A27).
  expect(api.calls.map(asked)).toEqual([
    'GET /coop',
    'GET /auth/me',
    'POST /coop',
  ]);
});

// Every tab shares the cookie (A27).
it.each([
  ['signed in as someone else', () => json({ ...identity(2), user_id: 'u-2' })],
  ['signed out', () => apiError(401, 'unauthorized', 'Missing bearer token.')],
])(
  'when another tab has since %s, the upload is not sent: the form says this login no longer works and keeps the draft',
  async (_name, me) => {
    const api = fakeApi(({ path }) =>
      path === '/auth/me'
        ? me()
        : path === '/coop'
          ? json(member0.body)
          : json(null, 404),
    );
    livePage('/coop', seededQueryClient({ viewer: member(0) }));
    await screen.findAllByRole('article');
    await fillRequired();
    await submit();
    expect(
      await screen.findByRole('status', { name: '投稿结果' }),
    ).toHaveTextContent('登录已经失效，请重新登录后再提交。');
    expect(within(form()).getByLabelText(/^公司/)).toHaveValue(
      '  Example Co.  ',
    );
    expect(api.count('GET', '/auth/me')).toBe(1);
    expect(api.count('POST', '/coop')).toBe(0);
    expect(sidebar()).toHaveTextContent('贡献数：0');
  },
);

it('a count that grew since login comes from the server: the account box, the level and the list follow, and the result stays', async () => {
  let lists = 0;
  const api = fakeApi(({ method, path }) =>
    method === 'POST' && path === '/coop'
      ? json({ ...pending.body, contribution_count: 2 }, 201)
      : path === '/coop'
        ? json(lists++ ? member2.body : member0.body)
        : json(null, 404),
  );
  const client = livePage('/coop', seededQueryClient({ viewer: member(0) }));
  await screen.findAllByRole('article');
  await fillRequired();
  await submit();
  expect(await screen.findByText('$40-45/hr')).toBeInTheDocument();
  expect(sidebar()).toHaveTextContent('贡献数：2');
  expect(screen.getByText('已公开贡献：2 条 · 当前等级 2')).toBeInTheDocument();
  expect(screen.getByRole('status', { name: '投稿结果' })).toHaveTextContent(
    '已私有收集',
  );
  expect(api.count('GET', '/coop')).toBe(2);
  expect(
    client.getQueryData(['viewer', 'member:u-1:0', 'coop']),
  ).toBeUndefined();
});

// The plan's choice (section 35, known): signing out here would remount the page and lose the draft (B27).
it('an upload the API refuses with 401 keeps the member, the draft and the form, and logs nobody out', async () => {
  const api = fakeApi(({ method, path }) =>
    method === 'POST' && path === '/coop'
      ? apiError(401, 'unauthorized', 'Unknown user. Log in again.')
      : path === '/coop'
        ? json(member0.body)
        : path === '/auth/me'
          ? json(identity(0))
          : json(null, 404),
  );
  const client = livePage('/coop', seededQueryClient({ viewer: member(0) }));
  await screen.findAllByRole('article');
  await fillRequired();
  await submit();
  expect(
    await screen.findByRole('status', { name: '投稿结果' }),
  ).toHaveTextContent('登录已经失效，请重新登录后再提交。');
  expect(within(form()).getByLabelText(/^公司/)).toHaveValue('  Example Co.  ');
  expect(sidebar()).toHaveTextContent('Synthetic Student');
  expect(client.getQueryData(meQuery.queryKey)).toEqual(member(0));
  expect(api.count('POST', '/coop')).toBe(1);
  expect(api.count('POST', '/auth/logout')).toBe(0);
});

it('a refused field is marked from the API’s answer, whose words never reach the page', async () => {
  fakeApi(({ method, path }) =>
    method === 'POST' && path === '/coop'
      ? apiError(422, 'invalid_input', 'company: PRIVATE VALUE is not allowed')
      : path === '/coop'
        ? json(member0.body)
        : json(null, 404),
  );
  livePage('/coop', seededQueryClient({ viewer: member(0) }));
  await screen.findAllByRole('article');
  await fillRequired();
  await submit();
  expect(
    await screen.findByRole('status', { name: '投稿结果' }),
  ).toHaveTextContent('有一项不符合要求，请检查后再提交。');
  expect(within(form()).getByLabelText(/^公司/)).toHaveAttribute(
    'aria-invalid',
    'true',
  );
  expect(screen.queryByText(/PRIVATE/)).not.toBeInTheDocument();
});

it('a lost connection keeps the draft and the upload is never sent again by itself', async () => {
  const api = fakeApi(({ method, path }) => {
    if (method === 'POST' && path === '/coop')
      throw new TypeError('Failed to fetch');
    return path === '/coop' ? json(member0.body) : json(null, 404);
  });
  livePage('/coop', seededQueryClient({ viewer: member(0) }));
  await screen.findAllByRole('article');
  await fillRequired();
  await submit();
  expect(
    await screen.findByRole('status', { name: '投稿结果' }),
  ).toHaveTextContent('投稿暂时提交不了，请稍后再试。你填的内容还在。');
  expect(within(form()).getByLabelText(/^公司/)).toHaveValue('  Example Co.  ');
  expect(api.count('POST', '/coop')).toBe(1);
});

it('the page’s 登录 is the account box’s login', async () => {
  const user = userEvent.setup();
  const api = fakeApi(({ path }) =>
    path === '/coop'
      ? json(guest.body)
      : path === '/auth/login-url'
        ? apiError(429, 'rate_limited', 'slow down')
        : json(null, 404),
  );
  livePage('/coop');
  await screen.findAllByRole('article');
  await user.click(
    within(screen.getByRole('region', { name: '查看权限' })).getByRole(
      'button',
      { name: '登录' },
    ),
  );
  await waitFor(() => expect(api.count('GET', '/auth/login-url')).toBe(1));
  expect(
    await screen.findByText('请求过于频繁，请稍后手动重试。'),
  ).toBeInTheDocument();
});

it('a member’s live page has no DOM axe violations', async () => {
  fakeApi(({ path }) =>
    path === '/coop' ? json(member2.body) : json(null, 404),
  );
  livePage('/coop', seededQueryClient({ viewer: member(2) }));
  await screen.findByText('$40-45/hr');
  const result = await axe(document.body, {
    rules: { 'color-contrast': { enabled: false } },
  });
  expect(result.violations).toEqual([]);
});
