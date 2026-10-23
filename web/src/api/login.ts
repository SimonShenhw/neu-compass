// Logging in with Google through the API's HttpOnly cookie, and out again (R2b).
//
// 1. startLogin: a fresh random state and the page to come back to go into sessionStorage, the only thing this site
//    keeps there (R0 14.6 keeps page content out of storage; a full-page trip to Google needs somewhere to keep
//    these two, and they are removed on the way back). GET /auth/login-url gives Google's address for that state and
//    for this site's own root as the redirect address; the whole page goes there.
// 2. Google sends the browser to /?code=&state= (or ?error=). The caller first takes code and state out of the
//    address bar (they must not stay in history or in a shared link), then finishLogin checks the state against the
//    stored one, used once: a missing or different state is refused before anything is sent. That is the login
//    forgery the API cannot stop on its own (R2a). Then POST /auth/callback in the cookie mode.
// 3. logout: POST /auth/logout. The cookie is HttpOnly, so only the API can end the session; a failure says so.
import {
  ApiError,
  apiErrorMessage,
  apiGet,
  apiPath,
  apiPost,
  isJsonObject,
  isTransientError,
  unreadableAnswer,
} from './client';
import { parseIdentity } from './queries';
import type { Member } from './queries';

export const PENDING_KEY = 'nc_login_pending';

export const LOGIN_MESSAGES = {
  failed: '登录没有完成，请再试一次。',
  forged: '登录没有完成，请重新登录。',
  domain: '只能用 husky.neu.edu 或 northeastern.edu 邮箱登录。',
  unverified: '这个 Google 账号的邮箱还没有验证，验证以后再登录。',
  storage: '这个浏览器不让本页暂存登录信息，所以没法登录。',
  logoutFailed: '没能退出登录，请再试一次。',
  loggedOut: '已退出登录。',
} as const;

// 32 random bytes, base64url without padding: 43 of A-Z a-z 0-9 _ -, inside the 16-128 /auth/login-url accepts.
export function makeState(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
}

// This site's own root: where Google sends the browser back. The API accepts only its WEB_ORIGINS plus "/".
export function redirectUri(): string {
  return `${window.location.origin}/`;
}

// A path on this site, or "/" for anything else: no other host, and nothing a browser reads as one.
export function safeReturnPath(value: unknown): string {
  if (typeof value !== 'string' || !value.startsWith('/')) return '/';
  try {
    // "//evil.test" and "/\evil.test" name another host. Dot segments can leave "//" at the front
    // ("/.//evil.test" -> "//evil.test"), so the result is checked as well.
    const url = new URL(value, window.location.origin);
    const path = `${url.pathname}${url.search}${url.hash}`;
    return url.origin === window.location.origin && !path.startsWith('//')
      ? path
      : '/';
  } catch {
    return '/';
  }
}

interface Pending {
  state: string;
  returnTo: string;
}

function rememberLogin(pending: Pending): void {
  try {
    sessionStorage.setItem(PENDING_KEY, JSON.stringify(pending));
  } catch {
    throw new LoginStorageError();
  }
}

// What startLogin stored, removed as it is read: a state is good for one return only.
export function takePendingLogin(): Pending | null {
  let text: string | null = null;
  try {
    text = sessionStorage.getItem(PENDING_KEY);
    sessionStorage.removeItem(PENDING_KEY);
  } catch {
    return null;
  }
  try {
    const value: unknown = JSON.parse(text ?? '');
    if (
      isJsonObject(value) &&
      typeof value.state === 'string' &&
      typeof value.returnTo === 'string'
    )
      return { state: value.state, returnTo: value.returnTo };
  } catch {
    // Not ours, or damaged: as good as nothing stored.
  }
  return null;
}

export class LoginStorageError extends Error {
  override name = 'LoginStorageError';
}

const LOOPBACK = new Set(['localhost', '127.0.0.1', '[::1]']);

// Google's address, or the dev API's fake one on this machine; never a script URL or plain http elsewhere.
function loginAddress(value: unknown): string {
  if (isJsonObject(value) && typeof value.url === 'string') {
    try {
      const url = new URL(value.url);
      if (
        url.protocol === 'https:' ||
        (url.protocol === 'http:' && LOOPBACK.has(url.hostname))
      )
        return url.href;
    } catch {
      // Falls through to the unreadable answer.
    }
  }
  throw unreadableAnswer();
}

// Leaves the page for Google, so it resolves only when that fails. `go` is window.location.assign; tests pass a spy.
export async function startLogin(
  returnTo: string,
  go: (url: string) => void,
): Promise<void> {
  const state = makeState();
  rememberLogin({ state, returnTo: safeReturnPath(returnTo) });
  try {
    const answer = await apiGet(apiPath('/auth/login-url'), {
      timeout: 'read',
      query: { state, redirect_uri: redirectUri() },
    });
    go(loginAddress(answer));
  } catch (error) {
    takePendingLogin();
    throw error;
  }
}

export type LoginReturn =
  | { kind: 'none' }
  | { kind: 'done'; member: Member; returnTo: string }
  | { kind: 'failed'; message: string; returnTo: string };

// Google's own return parameters, so the caller can take them out of the address bar before anything else happens.
export function isLoginReturn(pathname: string, search: string): boolean {
  const params = new URLSearchParams(search);
  return pathname === '/' && (params.has('code') || params.has('error'));
}

export async function finishLogin(search: string): Promise<LoginReturn> {
  const params = new URLSearchParams(search);
  const code = params.get('code');
  const error = params.get('error');
  if (code === null && error === null) return { kind: 'none' };
  const pending = takePendingLogin();
  const returnTo = safeReturnPath(pending?.returnTo);
  if (error !== null)
    // Google's own error code (e.g. access_denied) is shown only when it is a plain name, as in Streamlit.
    return {
      kind: 'failed',
      returnTo,
      message: /^[a-z_]{1,64}$/.test(error)
        ? `登录没有完成（${error}），请再试一次。`
        : LOGIN_MESSAGES.failed,
    };
  if (!pending || !code || params.get('state') !== pending.state)
    return { kind: 'failed', returnTo, message: LOGIN_MESSAGES.forged };
  try {
    const answer = await apiPost(
      apiPath('/auth/callback'),
      { code, session: 'cookie', redirect_uri: redirectUri() },
      { timeout: 'slow' },
    );
    return { kind: 'done', member: parseIdentity(answer), returnTo };
  } catch (failure) {
    return { kind: 'failed', returnTo, message: loginFailureMessage(failure) };
  }
}

// A wrong domain and an unverified email are said apart; every other refusal is one line (the user's choice, 10-23).
export function loginFailureMessage(error: unknown): string {
  if (error instanceof LoginStorageError) return LOGIN_MESSAGES.storage;
  if (error instanceof ApiError && error.status === 401) {
    if (error.reason === 'domain_not_allowed') return LOGIN_MESSAGES.domain;
    if (error.reason === 'email_unverified') return LOGIN_MESSAGES.unverified;
  }
  return isTransientError(error)
    ? apiErrorMessage(error)
    : LOGIN_MESSAGES.failed;
}

export async function logout(): Promise<void> {
  await apiPost(apiPath('/auth/logout'), undefined, { timeout: 'read' });
}
