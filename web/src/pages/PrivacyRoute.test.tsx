import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it } from 'vitest';
import { axe } from 'vitest-axe';
import { configQuery, createQueryClient } from '../api/queries';
import type { Member } from '../api/queries';
import deleted from '../fixtures/privacy/delete-ok.json';
import privacy from '../fixtures/privacy/privacy-90-days-feedback-contact.json';
import { FALLBACK_NOTICE } from '../layout/AppShell';
import { deleteMessages } from '../models/privacy';
import { addToCompare, getCompareList } from '../models/compareList';
import {
  apiError,
  asked,
  fakeApi,
  held,
  json,
  livePage,
} from '../test/fakeApi';
import type { Call } from '../test/fakeApi';
import { seededQueryClient } from '../test/withApi';

const MEMBER: Member = {
  kind: 'member',
  userId: 'u-1',
  email: 'synthetic.student@husky.neu.edu',
  displayName: 'Synthetic Student',
  contributionCount: 2,
};
// MEMBER as /auth/me gives it: asked again just before the deletion goes out.
const identity = {
  user_id: MEMBER.userId,
  email: MEMBER.email,
  display_name: MEMBER.displayName,
  contribution_count: MEMBER.contributionCount,
};
const intro = privacy.body.intro;
// The desktop sidebar (a page may have an aside of its own, as Co-op's does).
const sidebar = () =>
  screen.getByRole('navigation', { name: '主导航' }).closest('aside')!;
const fallback = () => screen.getByRole('status', { name: '内容更新' });
const refresh = () =>
  userEvent.click(
    within(sidebar()).getByRole('button', { name: '刷新页面内容' }),
  );
// /privacy answers with the fixture, /auth/me with MEMBER unless the test says otherwise, the deletion with what the
// test says.
function api(
  deletion: (call: Call) => Response | Promise<Response> = () =>
    json(deleted.body),
  me: () => Response = () => json(identity),
) {
  return fakeApi((call) =>
    call.path === '/privacy'
      ? json(privacy.body)
      : call.path === '/auth/me'
        ? me()
        : call.method === 'POST' && call.path === '/auth/delete-account'
          ? deletion(call)
          : json(null, 404),
  );
}
const signedOut = () =>
  waitFor(() =>
    expect(
      within(sidebar()).getByRole('button', { name: '用 NEU 邮箱登录' }),
    ).toBeInTheDocument(),
  );
async function deleteAccount() {
  const user = userEvent.setup();
  await user.click(
    await screen.findByRole('checkbox', { name: '我知道删除以后不能恢复' }),
  );
  await user.click(screen.getByRole('button', { name: '删除我的账号和投稿' }));
  return screen.findByRole('status', { name: '删除结果' });
}

it('the page shows the API’s own words, asked for once; a guest has no deletion', async () => {
  const calls = api();
  livePage('/privacy');
  expect(await screen.findByText(intro)).toBeInTheDocument();
  expect(calls.calls).toHaveLength(1);
  expect(calls.calls[0]).toMatchObject({
    method: 'GET',
    path: '/privacy',
    search: '',
    init: { credentials: 'include' },
  });
  expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  expect(
    screen.getByRole('heading', { level: 1 }).closest('header'),
  ).not.toHaveTextContent('游客');
});

it('while /auth/me is on its way the words show as to a guest, and the deletion comes with the member', async () => {
  const me = held();
  fakeApi(({ path }) =>
    path === '/auth/me'
      ? me.response
      : path === '/privacy'
        ? json(privacy.body)
        : json(null, 404),
  );
  const client = createQueryClient();
  client.setQueryData(configQuery.queryKey, {
    answer_feedback_enabled: false,
    login_available: true,
  });
  livePage('/privacy', client);
  expect(await screen.findByText(intro)).toBeInTheDocument();
  expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  me.answer(json(identity));
  expect(
    await screen.findByRole('checkbox', { name: '我知道删除以后不能恢复' }),
  ).toBeInTheDocument();
});

it('the words stay fresh for five minutes, so another visit asks nothing; 刷新页面内容 asks again', async () => {
  const user = userEvent.setup();
  const calls = api();
  livePage('/privacy');
  await screen.findByText(intro);
  await user.click(within(sidebar()).getByRole('link', { name: /培养方案/ }));
  await user.click(within(sidebar()).getByRole('link', { name: /数据与隐私/ }));
  expect(screen.getByText(intro)).toBeInTheDocument();
  expect(calls.count('GET', '/privacy')).toBe(1);
  await user.click(
    within(sidebar()).getByRole('button', { name: '刷新页面内容' }),
  );
  await waitFor(() => expect(calls.count('GET', '/privacy')).toBe(2));
});

it('a member deletes with exactly {"confirm": "delete"}; then the page is a guest’s, and the comparison and what was kept for them are gone, without asking the API to log out', async () => {
  const calls = api();
  const client = livePage('/privacy', seededQueryClient({ viewer: MEMBER }));
  act(() => {
    addToCompare('c-cs-5800');
  });
  client.setQueryData(['viewer', 'member:u-1:2', 'coop'], []);
  expect(await deleteAccount()).toHaveTextContent(deleteMessages.success);
  const request = calls.calls.find((call) => call.method === 'POST')!;
  expect(request.body).toEqual({ confirm: 'delete' });
  expect(request.init).toMatchObject({
    credentials: 'include',
    headers: { 'X-NEU-Compass': '1', 'Content-Type': 'application/json' },
  });
  await waitFor(() =>
    expect(
      within(sidebar()).getByRole('button', { name: '用 NEU 邮箱登录' }),
    ).toBeInTheDocument(),
  );
  expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  expect(screen.getByRole('status', { name: '删除结果' })).toHaveTextContent(
    deleteMessages.success,
  );
  expect(getCompareList()).toEqual([]);
  expect(
    client.getQueryData(['viewer', 'member:u-1:2', 'coop']),
  ).toBeUndefined();
  expect(calls.count('POST', '/auth/logout')).toBe(0);
  expect(calls.count('POST', '/auth/delete-account')).toBe(1);
  // Who is signed in was asked again just before (A27).
  expect(calls.calls.map(asked)).toEqual([
    'GET /privacy',
    'GET /auth/me',
    'POST /auth/delete-account',
  ]);
});

it('a 401 means the login no longer works: said, and the page is signed out', async () => {
  api(() => apiError(401, 'unauthorized', 'Unknown user.'));
  livePage('/privacy', seededQueryClient({ viewer: MEMBER }));
  expect(await deleteAccount()).toHaveTextContent(deleteMessages.expired);
  await signedOut();
});

// R5c drops an answer that comes after the page went; the account is gone all the same (A27).
it.each([
  ['a 200', () => json(deleted.body)],
  ['a 401', () => apiError(401, 'unauthorized', 'Unknown user.')],
])(
  '%s that comes after the page was left still signs out, and the comparison and what was kept go',
  async (_name, answer) => {
    const user = userEvent.setup();
    const deletion = held();
    const calls = api(() => deletion.response);
    const client = livePage('/privacy', seededQueryClient({ viewer: MEMBER }));
    act(() => {
      addToCompare('c-cs-5800');
    });
    client.setQueryData(['viewer', 'member:u-1:2', 'coop'], []);
    await user.click(
      await screen.findByRole('checkbox', { name: '我知道删除以后不能恢复' }),
    );
    await user.click(
      screen.getByRole('button', { name: '删除我的账号和投稿' }),
    );
    await waitFor(() =>
      expect(calls.count('POST', '/auth/delete-account')).toBe(1),
    );
    await user.click(within(sidebar()).getByRole('link', { name: /培养方案/ }));
    deletion.answer(answer());
    await signedOut();
    expect(getCompareList()).toEqual([]);
    expect(
      client.getQueryData(['viewer', 'member:u-1:2', 'coop']),
    ).toBeUndefined();
    expect(calls.count('POST', '/auth/logout')).toBe(0);
  },
);

// Every tab shares the cookie (A27).
it.each([
  [
    'signed in as someone else',
    () =>
      json({
        ...identity,
        user_id: 'u-2',
        email: 'synthetic.other@husky.neu.edu',
      }),
  ],
  ['signed out', () => apiError(401, 'unauthorized', 'Missing bearer token.')],
])(
  'when another tab has since %s, nothing is deleted: this login no longer works, and the page is signed out',
  async (_name, me) => {
    const calls = api(undefined, me);
    livePage('/privacy', seededQueryClient({ viewer: MEMBER }));
    expect(await deleteAccount()).toHaveTextContent(deleteMessages.expired);
    expect(calls.count('GET', '/auth/me')).toBe(1);
    expect(calls.count('POST', '/auth/delete-account')).toBe(0);
    await signedOut();
  },
);

it('when /auth/me gives no answer the page can read, the deletion goes out and its own answer says what happened', async () => {
  const calls = api(undefined, () =>
    apiError(503, 'service_unavailable', 'down'),
  );
  livePage('/privacy', seededQueryClient({ viewer: MEMBER }));
  expect(await deleteAccount()).toHaveTextContent(deleteMessages.success);
  expect(calls.count('POST', '/auth/delete-account')).toBe(1);
  await signedOut();
});

it.each([
  [
    'no connection',
    () => {
      throw new TypeError('Failed to fetch');
    },
  ],
  ['a 503', () => apiError(503, 'service_unavailable', 'down')],
  [
    'a proxy’s 502 page',
    () => new Response('<html>Bad gateway</html>', { status: 502 }),
  ],
  ['a 200 the page cannot read', () => json({ deleted: true })],
])(
  'after %s nobody knows whether the account went: said, the member stays, and nothing is sent again',
  async (_name, answer) => {
    const calls = api(answer);
    livePage('/privacy', seededQueryClient({ viewer: MEMBER }));
    expect(await deleteAccount()).toHaveTextContent(deleteMessages.uncertain);
    expect(sidebar()).toHaveTextContent('Synthetic Student');
    expect(
      screen.getByRole('checkbox', { name: '我知道删除以后不能恢复' }),
    ).toBeInTheDocument();
    expect(calls.count('POST', '/auth/delete-account')).toBe(1);
  },
);

it.each([
  ['403', () => apiError(403, 'csrf_rejected', 'Cross-site request refused.')],
  ['422', () => apiError(422, 'invalid_input', 'confirm: wrong word')],
])(
  'a %s refused the deletion: nothing was deleted, and the member stays',
  async (_name, answer) => {
    api(answer);
    livePage('/privacy', seededQueryClient({ viewer: MEMBER }));
    expect(await deleteAccount()).toHaveTextContent(deleteMessages.refused);
    expect(sidebar()).toHaveTextContent('Synthetic Student');
    expect(screen.queryByText(/Cross-site|wrong word/)).not.toBeInTheDocument();
  },
);

it('a failed /privacy says so, and 重试 asks again', async () => {
  const user = userEvent.setup();
  const answers = [
    () => apiError(503, 'service_unavailable', 'down'),
    () => json(privacy.body),
  ];
  const calls = fakeApi(({ path }) =>
    path === '/privacy' ? answers.shift()!() : json(null, 404),
  );
  livePage('/privacy');
  expect(
    await screen.findByText('隐私说明暂时加载不了，请稍后重试。'),
  ).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: '重试' }));
  expect(await screen.findByText(intro)).toBeInTheDocument();
  expect(calls.count('GET', '/privacy')).toBe(2);
});

it('while 重试 is on its way the page shows as loading, not as the failure', async () => {
  const user = userEvent.setup();
  const second = held();
  let tries = 0;
  fakeApi(({ path }) =>
    path === '/privacy'
      ? tries++
        ? second.response
        : apiError(503, 'service_unavailable', 'down')
      : json(null, 404),
  );
  livePage('/privacy');
  await user.click(await screen.findByRole('button', { name: '重试' }));
  await waitFor(() =>
    expect(
      screen.queryByText('隐私说明暂时加载不了，请稍后重试。'),
    ).not.toBeInTheDocument(),
  );
  expect(screen.getByText('正在加载')).toBeInTheDocument();
  second.answer(json(privacy.body));
  expect(await screen.findByText(intro)).toBeInTheDocument();
});

it('a temporary failure keeps the words and says so above the page; a definite answer does not', async () => {
  const answers = [
    () => json(privacy.body),
    () => apiError(503, 'service_unavailable', 'down'),
    () => apiError(404, 'not_found', 'gone'),
  ];
  fakeApi(({ path }) =>
    path === '/privacy' ? answers.shift()!() : json(null, 404),
  );
  livePage('/privacy');
  await screen.findByText(intro);
  expect(fallback()).toBeEmptyDOMElement();
  await refresh();
  await waitFor(() => expect(fallback()).toHaveTextContent(FALLBACK_NOTICE));
  expect(screen.getByText(intro)).toBeInTheDocument();
  await refresh();
  expect(
    await screen.findByText('隐私说明暂时加载不了，请稍后重试。'),
  ).toBeInTheDocument();
  expect(screen.queryByText(intro)).not.toBeInTheDocument();
  expect(fallback()).toBeEmptyDOMElement();
});

// After a success the failure stays on the query while it is asked again (only a query that never had data goes back
// to pending), so this is the path where the page itself has to tell a retry from the failure.
it('after a definite answer replaced the words, 重试 shows the page as loading until its answer', async () => {
  const user = userEvent.setup();
  const third = held();
  const answers = [
    () => json(privacy.body),
    () => apiError(404, 'not_found', 'gone'),
    () => third.response,
  ];
  fakeApi(({ path }) =>
    path === '/privacy' ? answers.shift()!() : json(null, 404),
  );
  livePage('/privacy');
  await screen.findByText(intro);
  await refresh();
  await user.click(await screen.findByRole('button', { name: '重试' }));
  await waitFor(() =>
    expect(
      screen.queryByText('隐私说明暂时加载不了，请稍后重试。'),
    ).not.toBeInTheDocument(),
  );
  expect(screen.getByText('正在加载')).toBeInTheDocument();
  third.answer(json(privacy.body));
  expect(await screen.findByText(intro)).toBeInTheDocument();
});

it('a member’s live page has no DOM axe violations', async () => {
  api();
  livePage('/privacy', seededQueryClient({ viewer: MEMBER }));
  await screen.findByRole('checkbox', { name: '我知道删除以后不能恢复' });
  const result = await axe(document.body, {
    rules: { 'color-contrast': { enabled: false } },
  });
  expect(result.violations).toEqual([]);
});
