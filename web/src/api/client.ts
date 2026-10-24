// The module that talks to the API (R2b); contracts.test.ts keeps fetch out of every other file but chatStream.ts,
// which reads /chat's answer as it arrives and shares the rules below.
//
// - Every request sends the API's HttpOnly session cookie (credentials: 'include'); the page never holds a token.
// - A write carries `X-NEU-Compass: 1`, and a JSON Content-Type when it has a body, as the API's CSRF check wants
//   (R2a). A read sends neither, so it needs no CORS preflight.
// - Each request has one of the four timeouts Streamlit uses (R0 0.5). Nothing here retries, and writes are never
//   retried anywhere: a question or an upload that timed out may still be running on the server.
// - A failure is an ApiError: the status, the API's error_type and Retry-After, and for a 422 the names of the
//   fields it refused. Never the API's `detail` text, which is English and can name internals; apiErrorMessage gives
//   the Chinese line instead (R0 0.6). Nothing is logged, so no course code in a path reaches the console (R0 14.1).
import type { paths } from './schema';

export const API_BASE_URL: string = __API_BASE_URL__;

export const TIMEOUT_MS = {
  quick: 5_000, // /config, /ready
  read: 8_000, // lists, programs, policies, the login address, feedback, logout
  write: 15_000, // account deletion
  slow: 30_000, // course details, Co-op, the login callback, /auth/me
} as const;
export type Timeout = keyof typeof TIMEOUT_MS;

export interface RequestOptions {
  timeout: Timeout;
  signal?: AbortSignal | undefined;
  query?: Readonly<Record<string, string | undefined>> | undefined;
}

type ParamNames<T extends string> =
  T extends `${string}{${infer Name}}${infer Rest}`
    ? Name | ParamNames<Rest>
    : never;
type PathArgs<T extends string> = [ParamNames<T>] extends [never]
  ? []
  : [Readonly<Record<ParamNames<T>, string>>];

// A path from the OpenAPI document with its parameters filled in, each percent-encoded. A route that the API renames
// or removes stops this from compiling once schema.ts is regenerated.
export function apiPath<T extends keyof paths & string>(
  template: T,
  ...args: PathArgs<T>
): string {
  const params: Readonly<Record<string, string>> = args[0] ?? {};
  return template.replace(/\{([^}]+)\}/g, (_, name: string) => {
    const value = params[name];
    if (value === undefined) throw new Error(`Missing path parameter ${name}`);
    // Encoding leaves "." and "..", which a URL reads as this path and the one above it, and an empty value names
    // another route: none of them can be what the page meant.
    if (value === '' || value === '.' || value === '..')
      throw new Error(`Path parameter ${name} cannot be "${value}"`);
    return encodeURIComponent(value);
  });
}

export function isJsonObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

// Sent with every request: the cookie, no HTTP cache, and a redirect is not followed (it is not this API's answer).
export const FETCH_OPTIONS = {
  credentials: 'include',
  cache: 'no-store',
  redirect: 'manual',
} as const satisfies RequestInit;

export function requestHeaders(
  method: 'GET' | 'POST',
  withBody: boolean,
): Record<string, string> {
  const headers: Record<string, string> = {};
  if (method === 'POST') headers['X-NEU-Compass'] = '1';
  if (withBody) headers['Content-Type'] = 'application/json';
  return headers;
}

// error_type and reason: plain lowercase names, anything else is dropped.
const NAME = /^[a-z_]{1,64}$/;
// The API names a refused field this way or writes `<field>` (api/exceptions.py).
const FIELD_NAME = /^[A-Za-z_][A-Za-z0-9_.]{0,63}$/;

export interface ApiErrorDetails {
  errorType?: string | null;
  retryAfter?: number | null;
  invalidFields?: readonly string[];
  reason?: string | null;
}

export class ApiError extends Error {
  override name = 'ApiError';
  // The HTTP status; 503 when the API could not be reached and 504 when it did not answer in time, as in Streamlit.
  readonly status: number;
  readonly errorType: string | null;
  // Seconds from Retry-After, only a whole number from 1 to 3600; anything else is unknown.
  readonly retryAfter: number | null;
  // For a 422: the fields the API refused, for the page to match against its own form. Never the reason text.
  readonly invalidFields: readonly string[];
  // A refused login's stable reason (the callback's 401, R2b), e.g. domain_not_allowed.
  readonly reason: string | null;

  constructor(status: number, details: ApiErrorDetails = {}) {
    super(`API ${status}`);
    this.status = status;
    this.errorType = details.errorType ?? null;
    this.retryAfter = details.retryAfter ?? null;
    this.invalidFields = details.invalidFields ?? [];
    this.reason = details.reason ?? null;
  }
}

// A 2xx that is not JSON, not the promised shape, or a redirect: an answer the page cannot read, as in Streamlit.
export const unreadableAnswer = () =>
  new ApiError(502, { errorType: 'invalid_response' });

export function retryAfterSeconds(value: string | null): number | null {
  const text = value?.trim() ?? '';
  if (!/^[0-9]{1,4}$/.test(text)) return null;
  const seconds = Number(text);
  return seconds >= 1 && seconds <= 3600 ? seconds : null;
}

// "company: String should have at least 1 character; role: Field required" -> ["company", "role"].
function refusedFields(detail: unknown): string[] {
  if (typeof detail !== 'string') return [];
  const names = detail.split('; ').flatMap((part) => {
    const end = part.indexOf(': ');
    const name = end > 0 ? part.slice(0, end) : '';
    return FIELD_NAME.test(name) ? [name] : [];
  });
  return [...new Set(names)];
}

export const plainName = (value: unknown): string | null =>
  typeof value === 'string' && NAME.test(value) ? value : null;

// The ApiError for an answer of 400 or more, from its status, headers and body text.
export function failureFrom(response: Response, text: string): ApiError {
  let body: unknown = null;
  try {
    body = JSON.parse(text);
  } catch {
    // Not JSON: a proxy's error page. The status alone decides what the page says.
  }
  const fields = isJsonObject(body) ? body : {};
  return new ApiError(response.status, {
    errorType: plainName(fields.error_type),
    retryAfter: retryAfterSeconds(response.headers.get('Retry-After')),
    invalidFields: response.status === 422 ? refusedFields(fields.detail) : [],
    reason: plainName(fields.reason),
  });
}

function result(response: Response, text: string): unknown {
  if (response.status === 204) return null;
  if (response.status >= 200 && response.status < 300) {
    try {
      return JSON.parse(text);
    } catch {
      throw unreadableAnswer();
    }
  }
  // A redirect (redirect: 'manual' makes it an opaque response with status 0) is not an answer from this API.
  if (response.status < 400) throw unreadableAnswer();
  throw failureFrom(response, text);
}

function address(path: string, query: RequestOptions['query']): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {}))
    if (value !== undefined) search.append(key, value);
  const text = search.toString();
  return `${API_BASE_URL}${path}${text ? `?${text}` : ''}`;
}

async function request(
  method: 'GET' | 'POST',
  path: string,
  body: string | undefined,
  options: RequestOptions,
): Promise<unknown> {
  const outer = options.signal;
  if (outer?.aborted) throw outer.reason;
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, TIMEOUT_MS[options.timeout]);
  const cancel = () => controller.abort(outer?.reason);
  outer?.addEventListener('abort', cancel, { once: true });
  try {
    let response: Response;
    let text: string;
    try {
      response = await fetch(address(path, options.query), {
        method,
        headers: requestHeaders(method, body !== undefined),
        ...(body === undefined ? {} : { body }),
        ...FETCH_OPTIONS,
        signal: controller.signal,
      });
      // The timeout covers the body too: an answer that stops halfway is as unfinished as no answer.
      text = await response.text();
    } catch {
      if (timedOut) throw new ApiError(504, { errorType: 'transport_timeout' });
      // The caller cancelled (the page went away): not a failure of the API, so the caller's reason goes through.
      if (outer?.aborted) throw outer.reason;
      throw new ApiError(503, { errorType: 'transport_error' });
    }
    return result(response, text);
  } finally {
    clearTimeout(timer);
    outer?.removeEventListener('abort', cancel);
  }
}

export function apiGet(
  path: string,
  options: RequestOptions,
): Promise<unknown> {
  return request('GET', path, undefined, options);
}

// `body: undefined` sends no body (logout); anything else is sent as JSON.
export function apiPost(
  path: string,
  body: unknown,
  options: RequestOptions,
): Promise<unknown> {
  return request(
    'POST',
    path,
    body === undefined ? undefined : JSON.stringify(body),
    options,
  );
}

// Temporary failures (a timeout, too many requests, the server or the connection) keep showing what the same visitor
// last saw; a definite answer (401, 403, 404, 422...) does not (R0 12).
export function isTransientError(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    (error.status === 408 || error.status === 429 || error.status >= 500)
  );
}

export const GENERIC_FAILURE = '请求未完成，请稍后手动重试。';

// The Chinese line for a failure, as Streamlit words it (app/api_client.py, R0 0.6). A 4xx gets the generic line
// here; a page that has its own words for a status or error_type says them instead.
export function apiErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return GENERIC_FAILURE;
  const later = error.retryAfter ? `${error.retryAfter} 秒后` : '稍后';
  if (error.status === 429) return `请求过于频繁，请${later}手动重试。`;
  if (error.status === 503)
    return error.errorType === 'service_busy'
      ? `服务正忙，请${later}手动重试。`
      : `服务暂不可用，请${later}手动重试。`;
  if (error.status === 408 || error.status === 504)
    return '请求超时，处理可能仍在进行；请稍后手动重试，避免重复提交。';
  if (error.status === 502 && error.errorType === 'invalid_response')
    return '服务返回了无法识别的内容，请稍后手动重试。';
  if (error.status >= 500) return '服务暂时出错，请稍后手动重试。';
  return GENERIC_FAILURE;
}
