import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  API_BASE_URL,
  ApiError,
  GENERIC_FAILURE,
  TIMEOUT_MS,
  apiErrorMessage,
  apiGet,
  apiPath,
  apiPost,
  isTransientError,
  retryAfterSeconds,
} from './client';

type Fetch = (url: string, init: RequestInit) => Promise<Response>;

function respond(response: Response | (() => Response)) {
  const fetch = vi.fn<Fetch>(async () =>
    typeof response === 'function' ? response() : response,
  );
  vi.stubGlobal('fetch', fetch);
  return fetch;
}
function json(body: unknown, status = 200, headers: HeadersInit = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  });
}
// A fetch that never answers; it rejects the way a real one does when its signal aborts.
function hang() {
  const fetch = vi.fn(
    (_url: string, init: RequestInit) =>
      new Promise<Response>((_, reject) => {
        init.signal?.addEventListener('abort', () =>
          reject(init.signal?.reason),
        );
      }),
  );
  vi.stubGlobal('fetch', fetch);
  return fetch;
}
async function failureOf(promise: Promise<unknown>): Promise<unknown> {
  try {
    await promise;
  } catch (error) {
    return error;
  }
  throw new Error('expected the request to fail');
}
const apiError = async (promise: Promise<unknown>) => {
  const error = await failureOf(promise);
  expect(error).toBeInstanceOf(ApiError);
  return error as ApiError;
};

afterEach(() => {
  vi.useRealTimers();
});

describe('where requests go', () => {
  it('tests build against the API on this machine', () => {
    expect(API_BASE_URL).toBe('http://127.0.0.1:8000');
  });

  it('uses the four timeouts Streamlit uses', () => {
    expect(TIMEOUT_MS).toEqual({
      quick: 5_000,
      read: 8_000,
      write: 15_000,
      slow: 30_000,
    });
  });

  it('fills path parameters from the OpenAPI templates, percent-encoded', () => {
    expect(apiPath('/config')).toBe('/config');
    expect(apiPath('/course/{course_id}', { course_id: 'c cs/6140?x#' })).toBe(
      '/course/c%20cs%2F6140%3Fx%23',
    );
    expect(
      apiPath('/programs/{program_id}/plans/{plan_id}/policies', {
        program_id: 'p 1',
        plan_id: 'q/2',
      }),
    ).toBe('/programs/p%201/plans/q%2F2/policies');
  });

  it('refuses a value that would ask for another path', () => {
    for (const value of ['', '.', '..'])
      expect(
        () => apiPath('/course/{course_id}', { course_id: value }),
        value,
      ).toThrow(`Path parameter course_id cannot be "${value}"`);
    expect(apiPath('/course/{course_id}', { course_id: '...' })).toBe(
      '/course/...',
    );
    expect(apiPath('/course/{course_id}', { course_id: '.x' })).toBe(
      '/course/.x',
    );
  });

  it('a template the API does not have does not compile, and a missing parameter throws', () => {
    // @ts-expect-error: not a path in openapi.json
    expect(apiPath('/no-such-route')).toBe('/no-such-route');
    // @ts-expect-error: the parameter is required
    expect(() => apiPath('/course/{course_id}')).toThrow(
      'Missing path parameter course_id',
    );
    // @ts-expect-error: the wrong parameter name
    expect(() => apiPath('/course/{course_id}', { id: 'x' })).toThrow(
      'Missing path parameter course_id',
    );
  });

  it('a read goes to the API origin with the cookie and no custom headers, so no preflight', async () => {
    const fetch = respond(json({ ok: true }));
    await expect(
      apiGet('/auth/login-url', {
        timeout: 'read',
        query: { state: 'a b&c', skipped: undefined },
      }),
    ).resolves.toEqual({ ok: true });
    expect(fetch).toHaveBeenCalledTimes(1);
    const [url, init] = fetch.mock.calls[0]!;
    expect(url).toBe('http://127.0.0.1:8000/auth/login-url?state=a+b%26c');
    expect(init).toMatchObject({
      method: 'GET',
      credentials: 'include',
      cache: 'no-store',
      redirect: 'manual',
    });
    expect(init.headers).toEqual({});
    expect(init).not.toHaveProperty('body');
    expect(init.signal).toBeInstanceOf(AbortSignal);
  });

  it('a read without a query has no question mark', async () => {
    const fetch = respond(json({}));
    await apiGet('/config', { timeout: 'quick', query: { a: undefined } });
    expect(fetch.mock.calls[0]![0]).toBe('http://127.0.0.1:8000/config');
  });

  it('a write sends JSON with the CSRF marker header', async () => {
    const fetch = respond(json({ deleted: true }));
    await apiPost(
      '/auth/delete-account',
      { confirm: 'delete' },
      {
        timeout: 'write',
      },
    );
    const [url, init] = fetch.mock.calls[0]!;
    expect(url).toBe('http://127.0.0.1:8000/auth/delete-account');
    expect(init).toMatchObject({
      method: 'POST',
      credentials: 'include',
      cache: 'no-store',
      redirect: 'manual',
      body: '{"confirm":"delete"}',
    });
    expect(init.headers).toEqual({
      'Content-Type': 'application/json',
      'X-NEU-Compass': '1',
    });
  });

  it('a write without a body sends only the marker header', async () => {
    const fetch = respond(new Response(null, { status: 204 }));
    await expect(
      apiPost('/auth/logout', undefined, { timeout: 'read' }),
    ).resolves.toBeNull();
    const init = fetch.mock.calls[0]![1];
    expect(init.headers).toEqual({ 'X-NEU-Compass': '1' });
    expect(init).not.toHaveProperty('body');
  });

  it('a falsy body is still sent', async () => {
    const fetch = respond(json({}));
    await apiPost('/feedback', null, { timeout: 'read' });
    expect(fetch.mock.calls[0]![1]).toMatchObject({ body: 'null' });
  });
});

describe('answers', () => {
  it('parses JSON from any 2xx and gives null for 204', async () => {
    respond(json({ coop_id: 'x' }, 201));
    await expect(apiPost('/coop', {}, { timeout: 'slow' })).resolves.toEqual({
      coop_id: 'x',
    });
    respond(new Response(null, { status: 204 }));
    await expect(apiGet('/config', { timeout: 'quick' })).resolves.toBeNull();
  });

  it('a 2xx that is not JSON is an unreadable answer (502 invalid_response)', async () => {
    for (const body of ['<html>proxy</html>', '', '{"a":']) {
      respond(new Response(body, { status: 200 }));
      const error = await apiError(apiGet('/config', { timeout: 'quick' }));
      expect([error.status, error.errorType]).toEqual([
        502,
        'invalid_response',
      ]);
    }
  });

  it('a redirect is not an answer from the API', async () => {
    const opaque = {
      status: 0,
      type: 'opaqueredirect',
      headers: new Headers(),
      text: async () => '',
    } as unknown as Response;
    for (const response of [opaque, new Response(null, { status: 302 })]) {
      respond(response);
      const error = await apiError(apiGet('/config', { timeout: 'quick' }));
      expect([error.status, error.errorType]).toEqual([
        502,
        'invalid_response',
      ]);
    }
  });

  it('a failure keeps the status, error_type and Retry-After, never the detail text', async () => {
    respond(
      json(
        {
          detail: 'Course not found',
          error_type: 'not_found',
          status_code: 404,
        },
        404,
      ),
    );
    const error = await apiError(apiGet('/course/x', { timeout: 'slow' }));
    expect(error.status).toBe(404);
    expect(error.errorType).toBe('not_found');
    expect(error.retryAfter).toBeNull();
    expect(error.invalidFields).toEqual([]);
    expect(error.message).toBe('API 404');
    expect(error.name).toBe('ApiError');
    expect(JSON.stringify(error)).not.toContain('Course not found');
    expect(Object.values(error)).not.toContain('Course not found');
    expect(apiErrorMessage(error)).toBe(GENERIC_FAILURE);
  });

  it('reads Retry-After only as a whole number of seconds from 1 to 3600', async () => {
    respond(
      json({ error_type: 'rate_limited' }, 429, { 'Retry-After': ' 30 ' }),
    );
    const error = await apiError(apiPost('/chat', {}, { timeout: 'slow' }));
    expect(error.retryAfter).toBe(30);
    expect(apiErrorMessage(error)).toBe('请求过于频繁，请30 秒后手动重试。');
    for (const [header, seconds] of [
      ['1', 1],
      ['3600', 3600],
      ['0007', 7],
      [' 7\t', 7],
      ['0', null],
      ['3601', null],
      ['12345', null],
      ['1.5', null],
      ['-1', null],
      ['+5', null],
      ['5s', null],
      ['', null],
      ['７', null],
      ['Wed, 21 Oct 2015 07:28:00 GMT', null],
    ] as const)
      expect(retryAfterSeconds(header), header).toBe(seconds);
    expect(retryAfterSeconds(null)).toBeNull();
  });

  it('keeps error_type only when it is a plain lowercase name', async () => {
    for (const [value, kept] of [
      ['service_busy', 'service_busy'],
      ['a'.repeat(64), 'a'.repeat(64)],
      ['a'.repeat(65), null],
      ['Service_Busy', null],
      ['busy-now', null],
      ['', null],
      [7, null],
      [null, null],
    ] as const) {
      respond(json({ detail: 'x', error_type: value }, 503));
      const error = await apiError(apiGet('/config', { timeout: 'quick' }));
      expect(error.errorType, String(value)).toBe(kept);
    }
  });

  it('a failure whose body is not JSON keeps its status alone', async () => {
    respond(
      new Response('<html>Bad gateway</html>', {
        status: 502,
        headers: { 'Retry-After': '9' },
      }),
    );
    const error = await apiError(apiGet('/config', { timeout: 'quick' }));
    expect([error.status, error.errorType, error.retryAfter]).toEqual([
      502,
      null,
      9,
    ]);
    respond(json(['not', 'an', 'object'], 500));
    const list = await apiError(apiGet('/config', { timeout: 'quick' }));
    expect([list.status, list.errorType]).toEqual([500, null]);
  });

  it('a 422 names the refused fields, and only fields', async () => {
    const cases: [unknown, string[]][] = [
      [
        'company: String should have at least 1 character; role: Field required',
        ['company', 'role'],
      ],
      ['plan.program_id: Field required', ['plan.program_id']],
      ['company: a; company: b', ['company']],
      ['<field>: Field required', []],
      ['invalid', []],
      [': no name', []],
      ['9lives: bad', []],
      ['Value error, A plan requires its matching program_id', []],
      [['company: x'], []],
      [undefined, []],
    ];
    for (const [detail, fields] of cases) {
      respond(json({ detail, error_type: 'invalid_input' }, 422));
      const error = await apiError(apiPost('/coop', {}, { timeout: 'slow' }));
      expect(error.invalidFields, String(detail)).toEqual(fields);
    }
    respond(json({ detail: 'company: no', error_type: 'client_error' }, 400));
    const other = await apiError(apiPost('/coop', {}, { timeout: 'slow' }));
    expect(other.invalidFields).toEqual([]);
  });

  it('never writes to the console, even when a course read fails', async () => {
    const spies = (['log', 'info', 'warn', 'error', 'debug'] as const).map(
      (name) => vi.spyOn(console, name),
    );
    respond(json({ detail: 'x', error_type: 'not_found' }, 404));
    await failureOf(apiGet('/course/c-cs-6140', { timeout: 'slow' }));
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      }),
    );
    await failureOf(apiGet('/course/c-cs-6140', { timeout: 'slow' }));
    for (const spy of spies) expect(spy).not.toHaveBeenCalled();
  });
});

describe('the connection', () => {
  it('a network failure is 503 transport_error', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      }),
    );
    const error = await apiError(apiGet('/config', { timeout: 'quick' }));
    expect([error.status, error.errorType]).toEqual([503, 'transport_error']);
    expect(apiErrorMessage(error)).toBe('服务暂不可用，请稍后手动重试。');
  });

  it('a body that breaks off is a network failure too', async () => {
    const broken = {
      status: 200,
      headers: new Headers(),
      text: async () => {
        throw new TypeError('network error');
      },
    } as unknown as Response;
    respond(broken);
    const error = await apiError(apiGet('/config', { timeout: 'quick' }));
    expect([error.status, error.errorType]).toEqual([503, 'transport_error']);
  });

  for (const [timeout, ms] of Object.entries(TIMEOUT_MS) as [
    keyof typeof TIMEOUT_MS,
    number,
  ][])
    it(`the ${timeout} timeout gives up after ${ms} ms with 504 transport_timeout`, async () => {
      vi.useFakeTimers();
      hang();
      const outcome = failureOf(apiGet('/config', { timeout }));
      let settled = false;
      void outcome.then(() => (settled = true));
      await vi.advanceTimersByTimeAsync(ms - 1);
      expect(settled).toBe(false);
      await vi.advanceTimersByTimeAsync(1);
      expect(settled).toBe(true);
      const error = await outcome;
      expect(error).toBeInstanceOf(ApiError);
      expect([
        (error as ApiError).status,
        (error as ApiError).errorType,
      ]).toEqual([504, 'transport_timeout']);
      expect(apiErrorMessage(error)).toBe(
        '请求超时，处理可能仍在进行；请稍后手动重试，避免重复提交。',
      );
    });

  it('the timeout also covers reading the body', async () => {
    vi.useFakeTimers();
    let signal: AbortSignal | undefined;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url: string, init: RequestInit) => {
        signal = init.signal ?? undefined;
        return {
          status: 200,
          headers: new Headers(),
          text: () =>
            new Promise<string>((_, reject) =>
              signal?.addEventListener('abort', () => reject(signal?.reason)),
            ),
        } as unknown as Response;
      }),
    );
    const outcome = failureOf(apiGet('/config', { timeout: 'quick' }));
    let settled = false;
    void outcome.then(() => (settled = true));
    await vi.advanceTimersByTimeAsync(TIMEOUT_MS.quick - 1);
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    expect(settled).toBe(true);
    expect(await outcome).toMatchObject({
      status: 504,
      errorType: 'transport_timeout',
    });
  });

  it('a request that answers in time leaves no timer behind', async () => {
    vi.useFakeTimers();
    respond(json({ ok: 1 }));
    await apiGet('/config', { timeout: 'slow' });
    expect(vi.getTimerCount()).toBe(0);
  });

  it('a cancelled request passes the caller’s reason through, not an ApiError', async () => {
    const fetch = hang();
    const controller = new AbortController();
    const outcome = failureOf(
      apiGet('/config', { timeout: 'slow', signal: controller.signal }),
    );
    await vi.waitFor(() => expect(fetch).toHaveBeenCalled());
    controller.abort();
    // The request itself is cancelled at once, not left to time out.
    expect(fetch.mock.calls[0]![1].signal?.aborted).toBe(true);
    const error = await outcome;
    expect(error).toBe(controller.signal.reason);
    expect(error).not.toBeInstanceOf(ApiError);
    expect((error as DOMException).name).toBe('AbortError');
  });

  it('a request cancelled before it starts never reaches fetch', async () => {
    const fetch = respond(json({}));
    const controller = new AbortController();
    controller.abort();
    const error = await failureOf(
      apiGet('/config', { timeout: 'slow', signal: controller.signal }),
    );
    expect(error).toBe(controller.signal.reason);
    expect(fetch).not.toHaveBeenCalled();
  });

  it('cancelling afterwards does not touch a request that has finished', async () => {
    respond(json({ ok: 1 }));
    const controller = new AbortController();
    await expect(
      apiGet('/config', { timeout: 'slow', signal: controller.signal }),
    ).resolves.toEqual({ ok: 1 });
    controller.abort();
  });
});

describe('what the page says', () => {
  const error = (
    status: number,
    errorType: string | null = null,
    retryAfter: number | null = null,
  ) => new ApiError(status, { errorType, retryAfter });

  it('words each failure as Streamlit does', () => {
    expect(GENERIC_FAILURE).toBe('请求未完成，请稍后手动重试。');
    for (const [failure, message] of [
      [error(429), '请求过于频繁，请稍后手动重试。'],
      [error(429, 'rate_limited', 12), '请求过于频繁，请12 秒后手动重试。'],
      [error(503, 'service_busy'), '服务正忙，请稍后手动重试。'],
      [error(503, 'service_busy', 5), '服务正忙，请5 秒后手动重试。'],
      [error(503, 'service_unavailable'), '服务暂不可用，请稍后手动重试。'],
      [error(503, null, 60), '服务暂不可用，请60 秒后手动重试。'],
      [
        error(408),
        '请求超时，处理可能仍在进行；请稍后手动重试，避免重复提交。',
      ],
      [
        error(504, 'transport_timeout'),
        '请求超时，处理可能仍在进行；请稍后手动重试，避免重复提交。',
      ],
      [
        error(502, 'invalid_response'),
        '服务返回了无法识别的内容，请稍后手动重试。',
      ],
      [error(502, 'upstream_error'), '服务暂时出错，请稍后手动重试。'],
      [error(500, 'internal_error'), '服务暂时出错，请稍后手动重试。'],
      [error(501), '服务暂时出错，请稍后手动重试。'],
      [error(599), '服务暂时出错，请稍后手动重试。'],
      [error(400), GENERIC_FAILURE],
      [error(401, 'unauthorized'), GENERIC_FAILURE],
      [error(404, 'not_found'), GENERIC_FAILURE],
      [error(409, 'conflict'), GENERIC_FAILURE],
      [error(422, 'invalid_input'), GENERIC_FAILURE],
      [error(499), GENERIC_FAILURE],
      [new Error('boom'), GENERIC_FAILURE],
      ['not an error', GENERIC_FAILURE],
    ] as const)
      expect(apiErrorMessage(failure), String(failure)).toBe(message);
  });

  it('counts a timeout, too many requests, the server and the connection as temporary', () => {
    for (const status of [408, 429, 500, 502, 503, 504, 599])
      expect(isTransientError(error(status)), String(status)).toBe(true);
    for (const status of [400, 401, 403, 404, 405, 409, 422, 499])
      expect(isTransientError(error(status)), String(status)).toBe(false);
    expect(isTransientError(new Error('x'))).toBe(false);
    expect(isTransientError(null)).toBe(false);
  });
});
