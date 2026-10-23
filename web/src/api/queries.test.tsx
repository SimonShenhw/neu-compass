import { QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, TIMEOUT_MS } from './client';
import {
  GUEST,
  PUBLIC_FRESH_MS,
  configQuery,
  createQueryClient,
  meQuery,
  parseConfig,
  parseIdentity,
  shownData,
  useConfig,
  useMe,
} from './queries';

function serve(...answers: (() => Response)[]) {
  const fetch = vi.fn<(url: string, init: RequestInit) => Promise<Response>>(
    async () => {
      const next = answers.length > 1 ? answers.shift()! : answers[0]!;
      return next();
    },
  );
  vi.stubGlobal('fetch', fetch);
  return fetch;
}
const json =
  (body: unknown, status = 200) =>
  () =>
    new Response(JSON.stringify(body), { status });
// A fetch that never answers; it rejects the way a real one does when its signal aborts.
function hang() {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      (_url: string, init: RequestInit) =>
        new Promise<Response>((_, reject) =>
          init.signal?.addEventListener('abort', () =>
            reject(init.signal?.reason),
          ),
        ),
    ),
  );
}
const member = {
  user_id: 'u-1',
  email: 'student@husky.neu.edu',
  display_name: 'Test Student',
  contribution_count: 2,
};
function wrapper(client = createQueryClient()) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
  };
}

afterEach(() => {
  vi.useRealTimers();
});

describe('the query client', () => {
  it('retries nothing and does not refetch when the window regains focus', () => {
    const defaults = createQueryClient().getDefaultOptions();
    expect(defaults.queries?.retry).toBe(false);
    expect(defaults.queries?.refetchOnWindowFocus).toBe(false);
    expect(defaults.mutations?.retry).toBe(false);
  });

  it('a failed read is not tried again', async () => {
    const fetch = serve(json({ error_type: 'service_busy' }, 503));
    const { result } = renderHook(() => useConfig(), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(result.current.error).toMatchObject({
      status: 503,
      errorType: 'service_busy',
    });
  });
});

describe('what a page shows after a failure', () => {
  it('keeps the last success through a temporary failure and drops it after a definite answer', () => {
    const data = { a: 1 };
    expect(shownData({ data, error: null })).toBe(data);
    expect(shownData({ data, error: undefined })).toBe(data);
    for (const status of [408, 429, 500, 502, 503, 504])
      expect(
        shownData({ data, error: new ApiError(status) }),
        String(status),
      ).toBe(data);
    for (const status of [400, 401, 403, 404, 409, 422])
      expect(
        shownData({ data, error: new ApiError(status) }),
        String(status),
      ).toBeUndefined();
    expect(
      shownData({ data, error: new Error('not from the API') }),
    ).toBeUndefined();
    expect(
      shownData({ data: undefined, error: new ApiError(503) }),
    ).toBeUndefined();
  });

  it('TanStack keeps the old data on a failed refetch, so shownData decides', async () => {
    const client = createQueryClient();
    serve(
      json({ answer_feedback_enabled: true, login_available: true }),
      json({ error_type: 'not_found' }, 404),
    );
    await client.fetchQuery(configQuery);
    await expect(
      client.fetchQuery({ ...configQuery, staleTime: 0 }),
    ).rejects.toMatchObject({ status: 404 });
    const state = client.getQueryState(configQuery.queryKey)!;
    expect(state.data).toEqual({
      answer_feedback_enabled: true,
      login_available: true,
    });
    expect(shownData(state)).toBeUndefined();
  });
});

describe('GET /config', () => {
  it('takes exactly the two flags', () => {
    expect(
      parseConfig({
        answer_feedback_enabled: false,
        login_available: true,
        extra: 'ignored',
      }),
    ).toEqual({ answer_feedback_enabled: false, login_available: true });
    for (const bad of [
      null,
      [],
      'x',
      {},
      { answer_feedback_enabled: 'true', login_available: true },
      { answer_feedback_enabled: true, login_available: 1 },
      { answer_feedback_enabled: true },
    ])
      expect(() => parseConfig(bad), JSON.stringify(bad)).toThrow(
        expect.objectContaining({ status: 502, errorType: 'invalid_response' }),
      );
  });

  it('gives up after the quick timeout, not before', async () => {
    vi.useFakeTimers();
    hang();
    let settled = false;
    const outcome = createQueryClient()
      .fetchQuery(configQuery)
      .catch((error: unknown) => error)
      .finally(() => (settled = true));
    await vi.advanceTimersByTimeAsync(TIMEOUT_MS.quick - 1);
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    expect(await outcome).toMatchObject({ status: 504 });
  });

  it('stays fresh for five minutes', async () => {
    expect(PUBLIC_FRESH_MS).toBe(300_000);
    vi.useFakeTimers({ toFake: ['Date'] });
    const client = createQueryClient();
    const fetch = serve(
      json({ answer_feedback_enabled: true, login_available: false }),
    );
    await client.fetchQuery(configQuery);
    expect(fetch.mock.calls[0]![0]).toBe('http://127.0.0.1:8000/config');
    vi.setSystemTime(Date.now() + PUBLIC_FRESH_MS - 1);
    await client.fetchQuery(configQuery);
    expect(fetch).toHaveBeenCalledTimes(1);
    vi.setSystemTime(Date.now() + 2);
    await client.fetchQuery(configQuery);
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it('the hook gives the parsed flags', async () => {
    serve(json({ answer_feedback_enabled: true, login_available: true }));
    const { result } = renderHook(() => useConfig(), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual({
      answer_feedback_enabled: true,
      login_available: true,
    });
  });
});

describe('GET /auth/me', () => {
  it('a 200 is a member, a 401 a guest', async () => {
    const client = createQueryClient();
    serve(json(member), json({ error_type: 'unauthorized' }, 401));
    await expect(client.fetchQuery(meQuery)).resolves.toEqual({
      kind: 'member',
      userId: 'u-1',
      email: 'student@husky.neu.edu',
      displayName: 'Test Student',
      contributionCount: 2,
    });
    await expect(
      client.fetchQuery({ ...meQuery, staleTime: 0 }),
    ).resolves.toEqual(GUEST);
  });

  it('any other failure is an error, not a guest', async () => {
    for (const status of [403, 500, 503]) {
      serve(json({}, status));
      await expect(
        createQueryClient().fetchQuery(meQuery),
        String(status),
      ).rejects.toMatchObject({ status });
    }
  });

  it('gives up after the slow timeout, not before', async () => {
    vi.useFakeTimers();
    hang();
    let settled = false;
    const outcome = createQueryClient()
      .fetchQuery(meQuery)
      .catch((error: unknown) => error)
      .finally(() => (settled = true));
    await vi.advanceTimersByTimeAsync(TIMEOUT_MS.slow - 1);
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    expect(await outcome).toMatchObject({ status: 504 });
  });

  it('never goes stale by itself', async () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    const client = createQueryClient();
    const fetch = serve(json(member));
    await client.fetchQuery(meQuery);
    vi.setSystemTime(Date.now() + 365 * 24 * 3600_000);
    await client.fetchQuery(meQuery);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0]![0]).toBe('http://127.0.0.1:8000/auth/me');
  });

  it('checks the identity as Streamlit does', () => {
    expect(parseIdentity({ user_id: 'u', email: 'e' })).toEqual({
      kind: 'member',
      userId: 'u',
      email: 'e',
      displayName: null,
      contributionCount: 0,
    });
    expect(
      parseIdentity({ ...member, display_name: null, session_token: null }),
    ).toMatchObject({ displayName: null });
    expect(parseIdentity({ ...member, contribution_count: 0 })).toMatchObject({
      contributionCount: 0,
    });
    for (const bad of [
      null,
      [],
      { ...member, user_id: '' },
      { ...member, user_id: 7 },
      { ...member, email: '' },
      { ...member, email: null },
      { ...member, contribution_count: -1 },
      { ...member, contribution_count: 1.5 },
      { ...member, contribution_count: true },
      { ...member, contribution_count: null },
      { ...member, contribution_count: '2' },
      { ...member, display_name: 3 },
      { ...member, session_token: 3 },
    ])
      expect(() => parseIdentity(bad), JSON.stringify(bad)).toThrow(
        expect.objectContaining({ status: 502, errorType: 'invalid_response' }),
      );
  });

  it('the hook gives the viewer', async () => {
    serve(json({ error_type: 'unauthorized' }, 401));
    const { result } = renderHook(() => useMe(), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(GUEST);
  });
});
