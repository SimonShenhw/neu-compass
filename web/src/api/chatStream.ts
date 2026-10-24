// The /chat answer as it arrives (R2b). POST /chat answers NDJSON, one event per line (api_contract.md,
// api/routes/chat.py). With client.ts the only module that calls fetch (contracts.test.ts): apiPost reads a whole
// answer, this reads it piece by piece.
//
// - The request is a write like any other (client.ts), and a failure before the stream starts is the same ApiError
//   (422, 404, 409, 429, 503...).
// - Then meta, zero or more tokens, and done; or an error instead of finishing. An error's `detail` is the API's
//   fixed line for the student (unlike an HTTP error's detail, which is never shown). The stream ends at the first
//   error or done.
// - Waiting for the answer to start, and for each next piece, takes 30 s at most, as Streamlit's read timeout does
//   (R0 0.5). Nothing is sent again by itself: every question counts against the day's model calls and writes
//   query_log.
// - A stream that breaks off, falls silent, or sends a line that is not one of the four events (or is longer than any
//   line the API sends) ends with an error
//   event in Streamlit's words, after what had arrived, so the page keeps the partial answer (R0 0.6). Streamlit
//   skips a line it cannot read; here it ends the stream. A cancel (the caller's signal) throws the caller's reason.
import {
  API_BASE_URL,
  ApiError,
  FETCH_OPTIONS,
  apiPath,
  failureFrom,
  isJsonObject,
  plainName,
  requestHeaders,
  unreadableAnswer,
} from './client';
import type { Schemas } from './types';

export type ChatRequest = Schemas['ChatRequest'];

export const STREAM_WAIT_MS = 30_000;
// No line the API sends comes near this (meta, the longest, is some tens of KB). A longer one, or a piece of one that
// has not ended yet, means the stream is broken, and the buffer never grows without end.
export const MAX_LINE_CHARS = 1_000_000;
// A line's length without its line ending, measured the same way whether the line has ended or is still arriving: a
// `\r\n` cut between two pieces must not change the answer (B26).
const lineLength = (line: string) =>
  line.endsWith('\r') ? line.length - 1 : line.length;

export const STREAM_MESSAGES = {
  lost: '连接中断。仅保留部分回答，未完整结束；请稍后手动重试。',
  incomplete: '回答流未完整结束；仅保留部分内容，请稍后手动重试。',
} as const;

export type ChatEvent =
  // The rest of meta (each course's evidence, notices, plan_context) is for the page to check (R3).
  | { type: 'meta'; meta: Readonly<Record<string, unknown>> }
  | { type: 'token'; text: string }
  | { type: 'error'; errorType: string; message: string }
  // The feedback receipt as sent, or null: the page binds it to the answer it showed, as Streamlit does.
  | { type: 'done'; feedback: unknown };

// One line as an event, or null when it is not one: the first must be meta, and meta comes only once.
function readEvent(line: string, first: boolean): ChatEvent | null {
  let value: unknown;
  try {
    value = JSON.parse(line);
  } catch {
    return null;
  }
  if (!isJsonObject(value)) return null;
  if (first)
    return value.type === 'meta' &&
      typeof value.matched_via === 'string' &&
      Array.isArray(value.results)
      ? { type: 'meta', meta: value }
      : null;
  if (value.type === 'token')
    return typeof value.text === 'string'
      ? { type: 'token', text: value.text }
      : null;
  if (value.type === 'error') {
    const errorType = plainName(value.error_type);
    return errorType !== null &&
      typeof value.detail === 'string' &&
      value.detail.trim() !== ''
      ? { type: 'error', errorType, message: value.detail }
      : null;
  }
  if (value.type === 'done')
    return { type: 'done', feedback: value.feedback ?? null };
  return null;
}

export async function* streamChat(
  request: ChatRequest,
  options: { signal?: AbortSignal | undefined } = {},
): AsyncGenerator<ChatEvent, void, undefined> {
  const outer = options.signal;
  if (outer?.aborted) throw outer.reason;
  const controller = new AbortController();
  let timedOut = false;
  const cancel = () => controller.abort(outer?.reason);
  outer?.addEventListener('abort', cancel, { once: true });
  // One wait of at most 30 s: for the answer to start, or for its next piece. The clock does not run while the
  // caller handles an event.
  async function within<T>(work: () => Promise<T>): Promise<T> {
    const timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, STREAM_WAIT_MS);
    try {
      return await work();
    } finally {
      clearTimeout(timer);
    }
  }
  // Before the stream starts, a wait that failed is an ApiError, as in client.ts; a cancel is the caller's reason.
  function failedBefore(): unknown {
    if (timedOut) return new ApiError(504, { errorType: 'transport_timeout' });
    if (outer?.aborted) return outer.reason;
    return new ApiError(503, { errorType: 'transport_error' });
  }
  try {
    let response: Response;
    try {
      response = await within(() =>
        fetch(`${API_BASE_URL}${apiPath('/chat')}`, {
          method: 'POST',
          headers: requestHeaders('POST', true),
          body: JSON.stringify(request),
          ...FETCH_OPTIONS,
          signal: controller.signal,
        }),
      );
    } catch {
      throw failedBefore();
    }
    const body = response.body;
    if (response.status !== 200 || body === null) {
      let text: string;
      try {
        text = await within(() => response.text());
      } catch {
        throw failedBefore();
      }
      // A redirect, a 204 or another 2xx is not this API's stream.
      throw response.status >= 400
        ? failureFrom(response, text)
        : unreadableAnswer();
    }
    const reader = body.getReader();
    const decoder = new TextDecoder();
    const broken: ChatEvent = {
      type: 'error',
      errorType: 'invalid_stream',
      message: STREAM_MESSAGES.incomplete,
    };
    let buffer = '';
    let first = true;
    for (;;) {
      let chunk: Awaited<ReturnType<typeof reader.read>>;
      try {
        chunk = await within(() => reader.read());
      } catch {
        if (!timedOut && outer?.aborted) throw outer.reason;
        yield {
          type: 'error',
          errorType: timedOut ? 'transport_timeout' : 'transport_error',
          message: STREAM_MESSAGES.lost,
        };
        return;
      }
      // A line can be cut between two pieces, and so can the bytes of one character; the last line may have no
      // newline.
      const text = chunk.done
        ? decoder.decode()
        : decoder.decode(chunk.value, { stream: true });
      buffer += text;
      // A piece without a newline ends no line, so the buffer is not split again: a long line arriving in many pieces
      // would otherwise take time in the square of its length.
      const lines =
        chunk.done || text.includes('\n') ? buffer.split('\n') : [buffer];
      buffer = chunk.done ? '' : (lines.pop() ?? '');
      for (const raw of lines) {
        if (lineLength(raw) > MAX_LINE_CHARS) {
          yield broken;
          return;
        }
        const line = raw.trim();
        if (line === '') continue;
        const event = readEvent(line, first);
        if (event === null) {
          yield broken;
          return;
        }
        first = false;
        yield event;
        if (event.type === 'error' || event.type === 'done') return;
      }
      if (lineLength(buffer) > MAX_LINE_CHARS) {
        yield broken;
        return;
      }
      if (chunk.done) {
        yield {
          type: 'error',
          errorType: 'incomplete_stream',
          message: STREAM_MESSAGES.incomplete,
        };
        return;
      }
    }
  } finally {
    outer?.removeEventListener('abort', cancel);
    // Whatever is left of the answer: after done or an error (the API has sent everything by then; DevTools shows
    // the request as cancelled, as httpx closes it in Streamlit), or when the caller stops reading.
    controller.abort();
  }
}
