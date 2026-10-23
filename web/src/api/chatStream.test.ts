import { afterEach, describe, expect, it, vi } from 'vitest';
import { STREAM_MESSAGES, STREAM_WAIT_MS, streamChat } from './chatStream';
import type { ChatEvent, ChatRequest } from './chatStream';
import { ApiError, apiErrorMessage } from './client';

type Fetch = (url: string, init: RequestInit) => Promise<Response>;
const encoder = new TextEncoder();
const line = (value: unknown) => `${JSON.stringify(value)}\n`;

const REQUEST: ChatRequest = {
  query: 'CS 5800 讲什么？',
  k: 5,
  allow_feedback_capture: false,
};
const META = {
  type: 'meta',
  matched_via: 'alias',
  retrieval_ms: 1.5,
  prompt_version: 'chat_v4',
  results: [
    {
      course_id: 'c-cs-5800',
      primary_code: 'CS 5800',
      primary_name: 'Algorithms',
      score: 1,
      answer_evidence: {},
    },
  ],
};
const ANSWER = ['按合成目录，', 'CS 5800 ', '是算法课。', ''];
const RECEIPT = {
  answer_id: 'a-1',
  answer_sha256: 'f'.repeat(64),
  feedback_token: 'synthetic-receipt',
};
const STREAM =
  line(META) +
  ANSWER.map((text) => line({ type: 'token', text })).join('') +
  line({ type: 'done', feedback: RECEIPT });
const EVENTS: ChatEvent[] = [
  { type: 'meta', meta: META },
  ...ANSWER.map((text) => ({ type: 'token' as const, text })),
  { type: 'done', feedback: RECEIPT },
];
const broken = (errorType: string): ChatEvent => ({
  type: 'error',
  errorType,
  message: STREAM_MESSAGES.incomplete,
});
const lost = (errorType: string): ChatEvent => ({
  type: 'error',
  errorType,
  message: STREAM_MESSAGES.lost,
});

// A body the test feeds piece by piece. It fails the way a browser's does when the request's signal aborts.
function pipe() {
  let feed!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      feed = controller;
    },
  });
  return {
    body,
    push: (piece: string | Uint8Array) =>
      feed.enqueue(typeof piece === 'string' ? encoder.encode(piece) : piece),
    end: () => feed.close(),
    fail: (error: unknown) => feed.error(error),
  };
}
type Pipe = ReturnType<typeof pipe>;
function answerWith(body: Pipe, init: ResponseInit = { status: 200 }) {
  const fetch = vi.fn<Fetch>(async (_url, request) => {
    request.signal?.addEventListener('abort', () =>
      body.fail(request.signal?.reason),
    );
    return new Response(body.body, init);
  });
  vi.stubGlobal('fetch', fetch);
  return fetch;
}
function serve(pieces: readonly (string | Uint8Array)[]) {
  const body = pipe();
  for (const piece of pieces) body.push(piece);
  body.end();
  return answerWith(body);
}
function respond(response: Response) {
  const fetch = vi.fn<Fetch>(async () => response);
  vi.stubGlobal('fetch', fetch);
  return fetch;
}
// A fetch that never answers; it rejects the way a real one does when its signal aborts.
function hang() {
  const fetch = vi.fn<Fetch>(
    (_url, init) =>
      new Promise<Response>((_answer, reject) =>
        init.signal?.addEventListener('abort', () =>
          reject(init.signal?.reason),
        ),
      ),
  );
  vi.stubGlobal('fetch', fetch);
  return fetch;
}
async function collect(stream: AsyncIterable<ChatEvent>) {
  const events: ChatEvent[] = [];
  for await (const event of stream) events.push(event);
  return events;
}
async function failureOf(work: Promise<unknown>): Promise<unknown> {
  try {
    await work;
  } catch (error) {
    return error;
  }
  throw new Error('expected the stream to fail');
}
const json = (body: unknown, status: number, headers: HeadersInit = {}) =>
  new Response(JSON.stringify(body), { status, headers });
const signalOf = (fetch: ReturnType<typeof vi.fn<Fetch>>) =>
  fetch.mock.calls[0]![1].signal!;

// Small, seeded and good enough to cut a stream in many places.
function cutter(seed: number) {
  let state = seed;
  return (below: number) => {
    state = (state * 1_103_515_245 + 12_345) % 2_147_483_648;
    return state % below;
  };
}
function cut(bytes: Uint8Array, at: readonly number[]): Uint8Array[] {
  const points = [0, ...[...new Set(at)].sort((a, b) => a - b), bytes.length];
  return points.slice(1).map((end, index) => bytes.slice(points[index], end));
}

afterEach(() => {
  vi.useRealTimers();
});

describe('a question and its answer', () => {
  it('is sent as a write with the cookie, and read event by event', async () => {
    const fetch = serve([STREAM]);
    expect(await collect(streamChat(REQUEST))).toEqual(EVENTS);
    expect(fetch).toHaveBeenCalledTimes(1);
    const [url, init] = fetch.mock.calls[0]!;
    expect(url).toBe('http://127.0.0.1:8000/chat');
    expect(init).toMatchObject({
      method: 'POST',
      credentials: 'include',
      cache: 'no-store',
      redirect: 'manual',
    });
    expect(init.headers).toEqual({
      'X-NEU-Compass': '1',
      'Content-Type': 'application/json',
    });
    expect(JSON.parse(String(init.body))).toEqual(REQUEST);
  });

  it('reads the same events wherever the bytes are cut, even inside a character', async () => {
    const bytes = encoder.encode(STREAM);
    for (let at = 1; at < bytes.length; at++) {
      serve(cut(bytes, [at]));
      expect(await collect(streamChat(REQUEST)), `cut at ${at}`).toEqual(
        EVENTS,
      );
    }
    const next = cutter(7);
    for (let run = 0; run < 200; run++) {
      const at = Array.from({ length: 1 + next(12) }, () => next(bytes.length));
      serve(cut(bytes, at));
      expect(await collect(streamChat(REQUEST)), `cuts ${at}`).toEqual(EVENTS);
    }
  });

  it('takes a last line without its newline, CRLF and blank lines', async () => {
    serve([STREAM.slice(0, -1)]);
    expect(await collect(streamChat(REQUEST))).toEqual(EVENTS);
    serve([`\r\n${STREAM.replaceAll('\n', '\r\n\r\n')}`]);
    expect(await collect(streamChat(REQUEST))).toEqual(EVENTS);
  });

  it('done without a receipt has null, and the receipt is passed on as sent', async () => {
    serve([line(META), line({ type: 'done' })]);
    expect(await collect(streamChat(REQUEST))).toEqual([
      { type: 'meta', meta: META },
      { type: 'done', feedback: null },
    ]);
    serve([line(META), line({ type: 'done', feedback: 'not a receipt' })]);
    expect((await collect(streamChat(REQUEST)))[1]).toEqual({
      type: 'done',
      feedback: 'not a receipt',
    });
  });

  it('ends at an error, which says the API’s own line for the student', async () => {
    const detail = '模型服务暂时出错，这条回答没有完成。请稍后再问一次。';
    const fetch = serve([
      line(META),
      line({ type: 'token', text: '按合成目录，' }),
      line({ type: 'error', error_type: 'upstream_error', detail }),
      line({ type: 'done' }),
    ]);
    expect(await collect(streamChat(REQUEST))).toEqual([
      { type: 'meta', meta: META },
      { type: 'token', text: '按合成目录，' },
      { type: 'error', errorType: 'upstream_error', message: detail },
    ]);
    // What is left of the answer is not read: the request is let go.
    expect(signalOf(fetch).aborted).toBe(true);
  });

  it('the day’s limit comes right after meta', async () => {
    const detail =
      '今天的回答次数已经用完，这次没有生成回答；检索到的课程照常列出。';
    serve([
      line(META),
      line({ type: 'error', error_type: 'daily_limit', detail }),
      line({ type: 'done' }),
    ]);
    expect(await collect(streamChat(REQUEST))).toEqual([
      { type: 'meta', meta: META },
      { type: 'error', errorType: 'daily_limit', message: detail },
    ]);
  });
});

describe('a broken stream', () => {
  it('that ends without done or an error says so after what arrived', async () => {
    serve([line(META), line({ type: 'token', text: '按合成目录，' })]);
    expect(await collect(streamChat(REQUEST))).toEqual([
      { type: 'meta', meta: META },
      { type: 'token', text: '按合成目录，' },
      broken('incomplete_stream'),
    ]);
    serve([]);
    expect(await collect(streamChat(REQUEST))).toEqual([
      broken('incomplete_stream'),
    ]);
  });

  it('ends at a line that is not one of the four events', async () => {
    const token = line({ type: 'token', text: 'x' });
    for (const [bad, before] of [
      [token, 0],
      [line({ ...META, results: {} }), 0],
      [line({ ...META, matched_via: 1 }), 0],
      [line({ type: 'done' }), 0],
      [line(META), 1],
      [line({ type: 'token', text: 7 }), 1],
      [line({ type: 'token' }), 1],
      [line({ type: 'error', error_type: 'Upstream', detail: 'x' }), 1],
      [line({ type: 'error', error_type: 'upstream_error' }), 1],
      [line({ type: 'error', error_type: 'upstream_error', detail: ' ' }), 1],
      [line({ type: 'tokens', text: 'x' }), 1],
      ['oops\n', 1],
      ['[1]\n', 1],
      ['"token"\n', 1],
    ] as const) {
      const fetch = serve([
        ...(before ? [line(META)] : []),
        bad,
        token,
        line({ type: 'done' }),
      ]);
      expect(await collect(streamChat(REQUEST)), bad).toEqual([
        ...(before ? [{ type: 'meta', meta: META }] : []),
        broken('invalid_stream'),
      ]);
      expect(fetch).toHaveBeenCalledTimes(1);
    }
  });

  it('that drops mid-answer keeps what arrived', async () => {
    const body = pipe();
    const fetch = answerWith(body);
    body.push(line(META) + line({ type: 'token', text: '按合成目录，' }));
    const stream = streamChat(REQUEST);
    const events = [(await stream.next()).value, (await stream.next()).value];
    body.fail(new TypeError('network error'));
    events.push((await stream.next()).value);
    expect(events).toEqual([
      { type: 'meta', meta: META },
      { type: 'token', text: '按合成目录，' },
      lost('transport_error'),
    ]);
    expect(await stream.next()).toEqual({ done: true, value: undefined });
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});

describe('before the stream starts', () => {
  it('a refusal is an ApiError, as for any request, and never sent again', async () => {
    for (const [response, expected] of [
      [
        json({ detail: 'query: String should have at least 1 character' }, 422),
        { status: 422, invalidFields: ['query'] },
      ],
      [
        json(
          { detail: '这个专业前缀对应多个项目', error_type: 'conflict' },
          409,
        ),
        { status: 409, errorType: 'conflict' },
      ],
      [
        json({ error_type: 'rate_limited' }, 429, { 'Retry-After': '7' }),
        { status: 429, retryAfter: 7 },
      ],
      [
        json({ error_type: 'service_busy' }, 503),
        { status: 503, errorType: 'service_busy' },
      ],
      [
        new Response(null, { status: 204 }),
        { status: 502, errorType: 'invalid_response' },
      ],
      [
        new Response(null, { status: 302, headers: { Location: '/x' } }),
        { status: 502, errorType: 'invalid_response' },
      ],
      [
        new Response(null, { status: 200 }),
        { status: 502, errorType: 'invalid_response' },
      ],
      [
        new Response(STREAM, { status: 201 }),
        { status: 502, errorType: 'invalid_response' },
      ],
    ] as const) {
      const fetch = respond(response);
      const error = await failureOf(collect(streamChat(REQUEST)));
      expect(error).toBeInstanceOf(ApiError);
      expect(error, String(response.status)).toMatchObject(expected);
      expect(JSON.stringify(error)).not.toContain('专业前缀');
      expect(fetch).toHaveBeenCalledTimes(1);
    }
  });

  it('no connection is 503 transport_error', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn<Fetch>(async () => {
        throw new TypeError('Failed to fetch');
      }),
    );
    expect(await failureOf(collect(streamChat(REQUEST)))).toMatchObject({
      status: 503,
      errorType: 'transport_error',
    });
  });
});

describe('waiting', () => {
  async function settlesAfter(work: Promise<unknown>, ms: number) {
    let settled = false;
    void work.then(
      () => (settled = true),
      () => (settled = true),
    );
    await vi.advanceTimersByTimeAsync(ms - 1);
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    expect(settled).toBe(true);
  }

  it('for the answer to start takes 30 s at most, then 504', async () => {
    expect(STREAM_WAIT_MS).toBe(30_000);
    vi.useFakeTimers();
    hang();
    const outcome = failureOf(collect(streamChat(REQUEST)));
    await settlesAfter(outcome, STREAM_WAIT_MS);
    const error = await outcome;
    expect(error).toMatchObject({
      status: 504,
      errorType: 'transport_timeout',
    });
    expect(apiErrorMessage(error)).toBe(
      '请求超时，处理可能仍在进行；请稍后手动重试，避免重复提交。',
    );
  });

  it('for each next piece takes 30 s at most, and the clock starts again with every piece', async () => {
    vi.useFakeTimers();
    const body = pipe();
    const fetch = answerWith(body);
    const stream = streamChat(REQUEST);
    body.push(line(META));
    expect((await stream.next()).value).toEqual({ type: 'meta', meta: META });
    const next = stream.next();
    await vi.advanceTimersByTimeAsync(20_000);
    body.push(line({ type: 'token', text: '按' }));
    expect((await next).value).toEqual({ type: 'token', text: '按' });
    const silent = stream.next();
    await settlesAfter(silent, STREAM_WAIT_MS);
    expect((await silent).value).toEqual(lost('transport_timeout'));
    expect(signalOf(fetch).aborted).toBe(true);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('the clock does not run while the page handles an event', async () => {
    vi.useFakeTimers();
    const body = pipe();
    answerWith(body);
    const stream = streamChat(REQUEST);
    body.push(line(META));
    await stream.next();
    await vi.advanceTimersByTimeAsync(40_000);
    body.push(line({ type: 'done' }));
    expect((await stream.next()).value).toEqual({
      type: 'done',
      feedback: null,
    });
  });

  it('leaves no timer behind', async () => {
    vi.useFakeTimers();
    serve([STREAM]);
    await collect(streamChat(REQUEST));
    expect(vi.getTimerCount()).toBe(0);
    respond(json({ error_type: 'rate_limited' }, 429));
    await failureOf(collect(streamChat(REQUEST)));
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe('cancelling', () => {
  it('before the start never reaches fetch and throws the caller’s reason', async () => {
    const fetch = hang();
    const controller = new AbortController();
    controller.abort(new DOMException('left the page', 'AbortError'));
    // The generator runs up to its first wait inside next(), so a fetch would already have been made here.
    const first = streamChat(REQUEST, { signal: controller.signal }).next();
    expect(fetch).not.toHaveBeenCalled();
    expect(await failureOf(first)).toBe(controller.signal.reason);
  });

  it('while waiting for the answer throws the caller’s reason, not an ApiError', async () => {
    const fetch = hang();
    const controller = new AbortController();
    const outcome = failureOf(
      collect(streamChat(REQUEST, { signal: controller.signal })),
    );
    await vi.waitFor(() => expect(fetch).toHaveBeenCalled());
    controller.abort(new DOMException('stop', 'AbortError'));
    expect(signalOf(fetch).aborted).toBe(true);
    expect(await outcome).toBe(controller.signal.reason);
  });

  it('mid-answer throws the caller’s reason, not an error event', async () => {
    const body = pipe();
    answerWith(body);
    const controller = new AbortController();
    const stream = streamChat(REQUEST, { signal: controller.signal });
    body.push(line(META));
    await stream.next();
    const next = stream.next();
    controller.abort(new DOMException('stop', 'AbortError'));
    expect(await failureOf(next)).toBe(controller.signal.reason);
  });

  it('a page that stops reading lets the request go', async () => {
    const body = pipe();
    const fetch = answerWith(body);
    body.push(line(META) + line({ type: 'token', text: 'x' }));
    for await (const event of streamChat(REQUEST)) {
      expect(event.type).toBe('meta');
      break;
    }
    expect(signalOf(fetch).aborted).toBe(true);
  });
});
