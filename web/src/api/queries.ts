// TanStack Query, set up the way Streamlit's page caches behaved (R2b; R0 12, app/view_cache.py):
// - nothing is retried by itself (every failure line says 手动重试), and neither focusing the window nor the network
//   coming back refetches anything; offline, a request still goes out and fails like any other, instead of waiting
//   for the network and then going out by itself (a write must never do that);
// - a public list stays fresh for five minutes;
// - after a temporary failure a page keeps showing what the same visitor last saw, after a definite answer
//   (401, 403, 404...) nothing old (shownData);
// - what depends on who is asking has the viewer in its key and goes at logout or a change of account (step 2);
//   policy evidence is never cached and never shown stale (its hook comes with R4).
// The pages' own hooks come with R3-R5; here are the client and the two hooks every page needs.
import { QueryClient, queryOptions, useQuery } from '@tanstack/react-query';
import {
  ApiError,
  apiGet,
  apiPath,
  isJsonObject,
  isTransientError,
  unreadableAnswer,
} from './client';
import type { Schemas } from './types';

export const PUBLIC_FRESH_MS = 5 * 60_000;

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
        networkMode: 'always',
      },
      mutations: { retry: false, networkMode: 'always' },
    },
  });
}

// What a page shows from a query: the last success, unless the latest failure was a definite answer.
export function shownData<T>(query: {
  data: T | undefined;
  error: unknown;
}): T | undefined {
  const { data, error } = query;
  return error === null || error === undefined || isTransientError(error)
    ? data
    : undefined;
}

export type PublicConfig = Schemas['PublicConfigResponse'];

export function parseConfig(value: unknown): PublicConfig {
  if (
    isJsonObject(value) &&
    typeof value.answer_feedback_enabled === 'boolean' &&
    typeof value.login_available === 'boolean'
  )
    return {
      answer_feedback_enabled: value.answer_feedback_enabled,
      login_available: value.login_available,
    };
  throw unreadableAnswer();
}

export const configQuery = queryOptions({
  queryKey: ['config'],
  queryFn: async ({ signal }) =>
    parseConfig(await apiGet(apiPath('/config'), { timeout: 'quick', signal })),
  staleTime: PUBLIC_FRESH_MS,
});

// `enabled: false` holds the request back: useSession does, while the address still carries Google's code.
export function useConfig(enabled = true) {
  return useQuery({ ...configQuery, enabled });
}

export type Member = {
  kind: 'member';
  userId: string;
  email: string;
  displayName: string | null;
  contributionCount: number;
};
export type Viewer = { kind: 'guest' } | Member;
export const GUEST: Viewer = { kind: 'guest' };

// The identity in an /auth/me or /auth/callback answer, checked as Streamlit's valid_identity does
// (app/state_manager.py): a malformed success is a failure, never half a login.
export function parseIdentity(value: unknown): Member {
  if (isJsonObject(value)) {
    const { user_id: userId, email } = value;
    const count = Object.hasOwn(value, 'contribution_count')
      ? value.contribution_count
      : 0;
    const displayName = value.display_name ?? null;
    const token = value.session_token ?? null;
    if (
      typeof userId === 'string' &&
      userId !== '' &&
      typeof email === 'string' &&
      email !== '' &&
      typeof count === 'number' &&
      Number.isInteger(count) &&
      count >= 0 &&
      (displayName === null || typeof displayName === 'string') &&
      (token === null || typeof token === 'string')
    )
      return {
        kind: 'member',
        userId,
        email,
        displayName,
        contributionCount: count,
      };
  }
  throw unreadableAnswer();
}

// Who is looking: 401 means a guest (the API also expires a cookie that no longer works). It changes only through
// login and logout, which update it here, so it never goes stale by itself.
export const meQuery = queryOptions({
  queryKey: ['me'],
  queryFn: async ({ signal }): Promise<Viewer> => {
    try {
      return parseIdentity(
        await apiGet(apiPath('/auth/me'), { timeout: 'slow', signal }),
      );
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) return GUEST;
      throw error;
    }
  },
  staleTime: Infinity,
});

export function useMe(enabled = true) {
  return useQuery({ ...meQuery, enabled });
}
