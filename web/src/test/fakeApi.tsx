import { render } from '@testing-library/react';
import type { QueryClient } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { vi } from 'vitest';
import { App } from '../App';
import { WithApi, seededQueryClient } from './withApi';

// A stand-in API for the live pages' tests (R5d): every request is kept, and answered by the test's function from its
// method and path. Nothing reaches the network.
export interface Call {
  method: string;
  path: string;
  init: RequestInit;
  body: unknown;
}
export function fakeApi(answer: (call: Call) => Response | Promise<Response>) {
  const calls: Call[] = [];
  const fetch = vi.fn(async (url: string, init: RequestInit = {}) => {
    const call: Call = {
      method: init.method ?? 'GET',
      path: new URL(url).pathname,
      init,
      body: typeof init.body === 'string' ? JSON.parse(init.body) : undefined,
    };
    calls.push(call);
    return answer(call);
  });
  vi.stubGlobal('fetch', fetch);
  return {
    calls,
    count: (method: string, path: string) =>
      calls.filter((call) => call.method === method && call.path === path)
        .length,
  };
}

export const json = (body: unknown, status = 200, headers?: HeadersInit) =>
  new Response(JSON.stringify(body), {
    status,
    ...(headers ? { headers } : {}),
  });

// The API's own error body (api/exceptions.py).
export const apiError = (status: number, errorType: string, detail: string) =>
  json({ detail, error_type: errorType, status_code: status }, status);

// An answer the test gives later: `answer` settles it, `fail` makes fetch reject as a lost connection does.
export function held() {
  let answer: (response: Response) => void = () => {};
  let fail: (error: unknown) => void = () => {};
  const response = new Promise<Response>((resolve, reject) => {
    answer = resolve;
    fail = reject;
  });
  return { response, answer, fail };
}

// The whole app at a path, with /config and /auth/me already known (seededQueryClient).
export function livePage(
  path: string,
  client: QueryClient = seededQueryClient(),
) {
  render(
    <WithApi client={client}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </WithApi>,
  );
  return client;
}
