import { act, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { PUBLIC_FRESH_MS } from '../api/queries';
import { READY_RETRY_MS, readyQuery } from '../api/ready';
import { fakeApi, json, livePage } from '../test/fakeApi';
import { seededQueryClient } from '../test/withApi';
import { FALLBACK_NOTICE } from './AppShell';

// The top bar's course count (R3e; R0 1): GET /ready, as Streamlit's hero showed it.
const READY = { status: 'ready', courses_indexed: 6469, bm25_corpus: 6469 };
const WARMING = { status: 'warming', courses_indexed: 0, bm25_corpus: 0 };
const NAMED = 'NEU 研究生课程目录';

// A client that knows /config and /auth/me, but not /ready yet.
function unseeded() {
  const client = seededQueryClient();
  client.removeQueries({ queryKey: readyQuery.queryKey });
  return client;
}
const refresh = () =>
  userEvent.click(
    within(
      screen.getByRole('navigation', { name: '主导航' }).closest('aside')!,
    ).getByRole('button', { name: '刷新页面内容' }),
  );

it('shows how many courses /ready says the API has indexed', async () => {
  const api = fakeApi(({ path }) =>
    path === '/ready' ? json(READY) : json(null, 404),
  );
  livePage('/programs', unseeded());
  expect(await screen.findByText('6,469 门课')).toBeInTheDocument();
  expect(screen.queryByText(NAMED)).not.toBeInTheDocument();
  expect(api.count('GET', '/ready')).toBe(1);
});

it('names the catalog without a number while /ready fails, and asks again 30 seconds later, then not by itself', async () => {
  // The fetch's own body reading stays on real timers.
  vi.useFakeTimers({
    toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'],
  });
  try {
    const answers = [json(WARMING, 503), json(READY)];
    const api = fakeApi(({ path }) =>
      path === '/ready' ? answers.shift()! : json(null, 404),
    );
    livePage('/programs', unseeded());
    await act(() => vi.advanceTimersByTimeAsync(10));
    expect(screen.getByText(NAMED)).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(READY_RETRY_MS - 11));
    expect(api.count('GET', '/ready')).toBe(1);
    await act(() => vi.advanceTimersByTimeAsync(11));
    expect(screen.getByText('6,469 门课')).toBeInTheDocument();
    expect(api.count('GET', '/ready')).toBe(2);
    await act(() => vi.advanceTimersByTimeAsync(2 * PUBLIC_FRESH_MS));
    expect(api.count('GET', '/ready')).toBe(2);
  } finally {
    vi.useRealTimers();
  }
});

it.each([
  ['the API warming up', WARMING],
  ['an answer it cannot read', { status: 'ready', courses_indexed: '6469' }],
])('names the catalog for %s', async (_, body) => {
  fakeApi(({ path }) => (path === '/ready' ? json(body) : json(null, 404)));
  livePage('/programs', unseeded());
  expect(await screen.findByText(NAMED)).toBeInTheDocument();
});

it('a refresh /ready cannot answer for a moment keeps the count and the shell says so; a definite answer drops it', async () => {
  const answers = [json(READY), json(WARMING, 503), json(null, 404)];
  fakeApi(({ path }) =>
    path === '/ready' ? answers.shift()! : json(null, 404),
  );
  livePage('/programs', unseeded());
  expect(await screen.findByText('6,469 门课')).toBeInTheDocument();
  await refresh();
  expect(await screen.findByText(FALLBACK_NOTICE)).toBeInTheDocument();
  expect(screen.getByText('6,469 门课')).toBeInTheDocument();
  await refresh();
  expect(await screen.findByText(NAMED)).toBeInTheDocument();
});

it('the comparison’s bar says what is chosen instead', async () => {
  fakeApi(({ path }) => (path === '/ready' ? json(READY) : json(null, 404)));
  livePage('/compare', unseeded());
  expect(
    await screen.findByText('已选 0 / 4 门 · 按加入的顺序'),
  ).toBeInTheDocument();
  expect(screen.queryByText('6,469 门课')).not.toBeInTheDocument();
});

it('the offline demo shell names the catalog and asks nothing', async () => {
  const api = fakeApi(() => json(READY));
  livePage('/programs-demo', unseeded());
  expect(await screen.findByText(NAMED)).toBeInTheDocument();
  expect(api.calls).toEqual([]);
});
