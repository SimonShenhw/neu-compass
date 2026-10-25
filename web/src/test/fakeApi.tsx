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
  // The query string, '' when there is none: a test that lists the calls sees one that should not be there.
  search: string;
  init: RequestInit;
  // A JSON body as parsed; any other body as it was sent.
  body: unknown;
}
function sent(body: RequestInit['body']): unknown {
  if (typeof body !== 'string') return undefined;
  try {
    return JSON.parse(body) as unknown;
  } catch {
    return body;
  }
}
export function fakeApi(answer: (call: Call) => Response | Promise<Response>) {
  const calls: Call[] = [];
  const fetch = vi.fn(async (url: string, init: RequestInit = {}) => {
    const { pathname, search } = new URL(url);
    const call: Call = {
      method: init.method ?? 'GET',
      path: pathname,
      search,
      init,
      body: sent(init.body),
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

// An answer the test gives later, with `answer`.
export function held() {
  let answer: (response: Response) => void = () => {};
  const response = new Promise<Response>((resolve) => {
    answer = resolve;
  });
  return { response, answer };
}
// A call as `METHOD /path?query`, for tests that list what was asked.
export const asked = ({ method, path, search }: Call) =>
  `${method} ${path}${search}`;

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
