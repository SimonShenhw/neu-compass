import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { LOCAL_API, PRODUCTION_API } from './apiBase';
import { ApiError } from './client';
import {
  LOGIN_MESSAGES,
  LoginStorageError,
  PENDING_KEY,
  finishLogin,
  isLoginReturn,
  loginAddress,
  loginFailureMessage,
  logout,
  makeState,
  redirectUri,
  safeReturnPath,
  startLogin,
  takePendingLogin,
} from './login';

type Fetch = (url: string, init: RequestInit) => Promise<Response>;
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status });
function serve(answer: () => Response) {
  const fetch = vi.fn<Fetch>(async () => answer());
  vi.stubGlobal('fetch', fetch);
  return fetch;
}
const member = {
  user_id: 'u-1',
  email: 'synthetic.student@husky.neu.edu',
  display_name: 'Synthetic Student',
  contribution_count: 3,
  session_token: null,
};
const STATE = 'synthetic-state-0123456789abcdefghijklmnopq';
const ORIGIN = window.location.origin;
const pending = (state = STATE, returnTo = '/compare') =>
  sessionStorage.setItem(PENDING_KEY, JSON.stringify({ state, returnTo }));

beforeEach(() => sessionStorage.clear());
afterEach(() => sessionStorage.clear());

// The other tests compare with these constants, so only this one notices a sentence that changed (B26).
it('says everything about logging in and out in these words', () => {
  expect(LOGIN_MESSAGES).toEqual({
    failed: '登录没有完成，请再试一次。',
    forged: '登录没有完成，请重新登录。',
    domain: '只能用 husky.neu.edu 或 northeastern.edu 邮箱登录。',
    unverified: '这个 Google 账号的邮箱还没有验证，验证以后再登录。',
    storage: '这个浏览器不让本页暂存登录信息，所以没法登录。',
    notKept:
      '登录状态没有保存下来（可能是浏览器不让本站使用 cookie），请再登录一次。',
    logoutFailed: '没能退出登录，请再试一次。',
    loggedOut: '已退出登录。',
  });
});

describe('the state', () => {
  it('is 32 random bytes as 43 base64url characters, new every time', () => {
    const states = new Set(Array.from({ length: 200 }, makeState));
    expect(states.size).toBe(200);
    for (const state of states) expect(state).toMatch(/^[A-Za-z0-9_-]{43}$/);
  });

  it('comes from the browser’s cryptographic random source', () => {
    const random = vi
      .spyOn(crypto, 'getRandomValues')
      .mockImplementation(<T extends ArrayBufferView | null>(array: T): T => {
        if (array instanceof Uint8Array) array.fill(255);
        return array;
      });
    expect(makeState()).toBe(`${'_'.repeat(42)}8`);
    expect(random).toHaveBeenCalledTimes(1);
    expect(random.mock.calls[0]![0]).toEqual(new Uint8Array(32).fill(255));
  });

  it('Google sends the browser back to this site’s own root', () => {
    expect(redirectUri()).toBe(`${ORIGIN}/`);
  });
});

describe('the page to come back to', () => {
  it('is a path on this site or the root', () => {
    for (const [value, path] of [
      ['/', '/'],
      ['/compare', '/compare'],
      ['/course/CS-6140?tab=1#top', '/course/CS-6140?tab=1#top'],
      ['/%2F%2Fevil.test', '/%2F%2Fevil.test'],
      ['//evil.test/x', '/'],
      ['/\\evil.test', '/'],
      ['/\t/evil.test/x', '/'],
      ['/.//evil.test', '/'],
      ['/%2e//evil.test', '/'],
      ['/a//b', '/a//b'],
      ['https://evil.test/', '/'],
      [`${ORIGIN}/compare`, '/'],
      ['javascript:alert(1)', '/'],
      ['compare', '/'],
      ['', '/'],
      [7, '/'],
      [null, '/'],
      [undefined, '/'],
    ] as const)
      expect(safeReturnPath(value), String(value)).toBe(path);
  });
});

describe('starting a login', () => {
  it('keeps the state and the page, then leaves for Google’s address', async () => {
    const fetch = serve(() =>
      json({ url: 'https://accounts.google.com/o/oauth2/v2/auth?state=x' }),
    );
    const go = vi.fn();
    await startLogin('/course/CS-6140?x=1', go);
    const stored = JSON.parse(sessionStorage.getItem(PENDING_KEY)!) as {
      state: string;
      returnTo: string;
    };
    expect(stored.returnTo).toBe('/course/CS-6140?x=1');
    expect(stored.state).toMatch(/^[A-Za-z0-9_-]{43}$/);
    const [url, init] = fetch.mock.calls[0]!;
    const address = new URL(url);
    expect(address.pathname).toBe('/auth/login-url');
    expect(Object.fromEntries(address.searchParams)).toEqual({
      state: stored.state,
      redirect_uri: `${ORIGIN}/`,
    });
    expect(init.method).toBe('GET');
    expect(go).toHaveBeenCalledWith(
      'https://accounts.google.com/o/oauth2/v2/auth?state=x',
    );
  });

  it('stores only a path on this site', async () => {
    serve(() => json({ url: 'https://accounts.google.com/' }));
    await startLogin('//evil.test/', vi.fn());
    expect(
      JSON.parse(sessionStorage.getItem(PENDING_KEY)!) as { returnTo: string },
    ).toMatchObject({ returnTo: '/' });
  });

  it('goes to the dev API’s fake Google on this machine, but nowhere odd', async () => {
    for (const url of [
      'http://127.0.0.1:8000/__dev/google?state=x',
      'https://accounts.google.com:443/o/oauth2/v2/auth',
    ]) {
      serve(() => json({ url }));
      const go = vi.fn();
      await startLogin('/', go);
      expect(go).toHaveBeenCalledWith(new URL(url).href);
    }
    for (const url of [
      'javascript:alert(1)',
      'http://evil.test/',
      'https://evil.test/',
      'https://accounts.google.com.evil.test/',
      'http://accounts.google.com/',
      'https://user:secret@accounts.google.com/',
      'http://localhost:8000/__dev/google',
      'http://127.0.0.1:9999/__dev/google',
      'data:text/html,x',
      'not a url',
      7,
    ]) {
      serve(() => json({ url }));
      const go = vi.fn();
      await expect(startLogin('/', go), String(url)).rejects.toMatchObject({
        status: 502,
        errorType: 'invalid_response',
      });
      expect(go).not.toHaveBeenCalled();
      expect(sessionStorage.getItem(PENDING_KEY)).toBeNull();
    }
  });

  it('a bundle for the real API goes to Google’s page and nowhere else', () => {
    const google = 'https://accounts.google.com/o/oauth2/v2/auth?state=x';
    expect(loginAddress({ url: google }, PRODUCTION_API)).toBe(google);
    for (const url of [
      'http://127.0.0.1:8000/__dev/google',
      `${PRODUCTION_API}/__dev/google`,
    ])
      expect(() => loginAddress({ url }, PRODUCTION_API), url).toThrow(
        expect.objectContaining({ status: 502 }),
      );
    expect(loginAddress({ url: `${LOCAL_API}/__dev/google` }, LOCAL_API)).toBe(
      `${LOCAL_API}/__dev/google`,
    );
  });

  it('a failure to get the address leaves nothing stored', async () => {
    serve(() => json({ error_type: 'service_unavailable' }, 503));
    const go = vi.fn();
    const error = await startLogin('/', go).catch((e: unknown) => e);
    expect(error).toMatchObject({ status: 503 });
    expect(go).not.toHaveBeenCalled();
    expect(sessionStorage.getItem(PENDING_KEY)).toBeNull();
    expect(loginFailureMessage(error)).toBe('服务暂不可用，请稍后手动重试。');
  });

  it('without sessionStorage there is no login, and no request', async () => {
    const fetch = serve(() => json({ url: 'https://accounts.google.com/' }));
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError');
    });
    const error = await startLogin('/', vi.fn()).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(LoginStorageError);
    expect(loginFailureMessage(error)).toBe(LOGIN_MESSAGES.storage);
    expect(fetch).not.toHaveBeenCalled();
  });
});

describe('what was stored', () => {
  it('is read once', () => {
    pending();
    expect(takePendingLogin()).toEqual({ state: STATE, returnTo: '/compare' });
    expect(takePendingLogin()).toBeNull();
  });

  it('is nothing when damaged or not ours', () => {
    for (const text of [
      '{',
      'null',
      '[]',
      '{"state":1,"returnTo":"/"}',
      '{"state":"x"}',
      // Only what makeState makes: 43 of A-Z a-z 0-9 _ -.
      '{"state":"","returnTo":"/"}',
      `{"state":"${STATE.slice(1)}","returnTo":"/"}`,
      `{"state":"${STATE}x","returnTo":"/"}`,
      `{"state":"${STATE.slice(1)}.","returnTo":"/"}`,
    ]) {
      sessionStorage.setItem(PENDING_KEY, text);
      expect(takePendingLogin(), text).toBeNull();
      expect(sessionStorage.getItem(PENDING_KEY)).toBeNull();
    }
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError');
    });
    expect(takePendingLogin()).toBeNull();
  });
});

describe('coming back from Google', () => {
  it('is only the root with code or error', () => {
    expect(isLoginReturn('/', '?code=x&state=y')).toBe(true);
    expect(isLoginReturn('/', '?error=access_denied')).toBe(true);
    expect(isLoginReturn('/', '?state=y')).toBe(false);
    expect(isLoginReturn('/', '')).toBe(false);
    expect(isLoginReturn('/compare', '?code=x&state=y')).toBe(false);
  });

  it('nothing to do without code or error', async () => {
    const fetch = serve(() => json(member));
    pending();
    await expect(finishLogin('?state=x')).resolves.toEqual({ kind: 'none' });
    expect(fetch).not.toHaveBeenCalled();
    expect(sessionStorage.getItem(PENDING_KEY)).not.toBeNull();
  });

  it('logs in with the cookie when the state matches, once', async () => {
    const fetch = serve(() => json(member));
    pending();
    const search = `?code=synthetic-code&state=${STATE}`;
    await expect(finishLogin(search)).resolves.toEqual({
      kind: 'done',
      returnTo: '/compare',
      member: {
        kind: 'member',
        userId: 'u-1',
        email: 'synthetic.student@husky.neu.edu',
        displayName: 'Synthetic Student',
        contributionCount: 3,
      },
    });
    const [url, init] = fetch.mock.calls[0]!;
    expect(url).toBe('http://127.0.0.1:8000/auth/callback');
    expect(JSON.parse(String(init.body))).toEqual({
      code: 'synthetic-code',
      session: 'cookie',
      redirect_uri: `${ORIGIN}/`,
    });
    expect(init.headers).toMatchObject({ 'X-NEU-Compass': '1' });
    expect(sessionStorage.getItem(PENDING_KEY)).toBeNull();
    // The same address again: the state was used up, so nothing is sent.
    await expect(finishLogin(search)).resolves.toMatchObject({
      kind: 'failed',
      message: LOGIN_MESSAGES.forged,
      returnTo: '/',
    });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('refuses a state it did not make, and sends nothing', async () => {
    for (const [stored, search] of [
      [false, `?code=c&state=${STATE}`],
      [true, '?code=c&state=another-state-0123456789abcdef'],
      [true, '?code=c'],
      [true, `?code=&state=${STATE}`],
      [true, `?code=c&state=${STATE}x`],
    ] as const) {
      const fetch = serve(() => json(member));
      if (stored) pending();
      await expect(finishLogin(search), search).resolves.toEqual({
        kind: 'failed',
        message: LOGIN_MESSAGES.forged,
        returnTo: stored ? '/compare' : '/',
      });
      expect(fetch).not.toHaveBeenCalled();
      expect(sessionStorage.getItem(PENDING_KEY)).toBeNull();
    }
  });

  it('Google’s own error names its code only when it is a plain name, and uses the state up', async () => {
    const fetch = serve(() => json(member));
    pending();
    await expect(
      finishLogin(`?error=access_denied&state=${STATE}`),
    ).resolves.toEqual({
      kind: 'failed',
      returnTo: '/compare',
      message: '登录没有完成（access_denied），请再试一次。',
    });
    expect(sessionStorage.getItem(PENDING_KEY)).toBeNull();
    pending();
    await expect(
      finishLogin(`?error=%3Cb%3Ex&state=${STATE}`),
    ).resolves.toMatchObject({ message: LOGIN_MESSAGES.failed });
    expect(fetch).not.toHaveBeenCalled();
  });

  it('an error link this tab’s login did not start shows none of its words', async () => {
    const words = 'your_account_is_locked_call_the_help_desk_now';
    for (const [stored, search] of [
      [false, `?error=${words}`],
      [false, `?error=${words}&state=${STATE}`],
      [true, `?error=${words}&state=another-state-0123456789abcdef`],
      [true, `?error=${words}`],
    ] as const) {
      if (stored) pending();
      const result = await finishLogin(search);
      expect(result, search).toEqual({
        kind: 'failed',
        message: LOGIN_MESSAGES.forged,
        returnTo: stored ? '/compare' : '/',
      });
      expect(JSON.stringify(result)).not.toContain(words);
      expect(sessionStorage.getItem(PENDING_KEY)).toBeNull();
    }
  });

  it('the stored page to come back to is checked again', async () => {
    serve(() => json(member));
    pending(STATE, '//evil.test/x');
    await expect(finishLogin(`?code=c&state=${STATE}`)).resolves.toMatchObject({
      kind: 'done',
      returnTo: '/',
    });
    pending(STATE, 'https://evil.test/');
    await expect(
      finishLogin(`?error=access_denied&state=${STATE}`),
    ).resolves.toMatchObject({ kind: 'failed', returnTo: '/' });
  });

  it('says a wrong domain and an unverified email apart, and nothing more', async () => {
    for (const [status, body, message] of [
      [401, { reason: 'domain_not_allowed' }, LOGIN_MESSAGES.domain],
      [401, { reason: 'email_unverified' }, LOGIN_MESSAGES.unverified],
      [401, { reason: 'token_exchange_rejected' }, LOGIN_MESSAGES.failed],
      [401, { reason: 'Domain_Not_Allowed' }, LOGIN_MESSAGES.failed],
      [401, {}, LOGIN_MESSAGES.failed],
      [403, { error_type: 'csrf_rejected' }, LOGIN_MESSAGES.failed],
      [422, { error_type: 'invalid_input' }, LOGIN_MESSAGES.failed],
      [403, { reason: 'domain_not_allowed' }, LOGIN_MESSAGES.failed],
      [503, { error_type: 'service_busy' }, '服务正忙，请稍后手动重试。'],
      [
        200,
        { ...member, user_id: '' },
        '服务返回了无法识别的内容，请稍后手动重试。',
      ],
    ] as const) {
      serve(() => json(body, status));
      pending();
      await expect(
        finishLogin(`?code=c&state=${STATE}`),
        JSON.stringify(body),
      ).resolves.toEqual({ kind: 'failed', returnTo: '/compare', message });
    }
  });

  it('a refused login never shows the API’s English detail', () => {
    const error = new ApiError(401, { reason: 'domain_not_allowed' });
    expect(loginFailureMessage(error)).toBe(LOGIN_MESSAGES.domain);
    expect(loginFailureMessage(new Error('Email domain not allowed'))).toBe(
      LOGIN_MESSAGES.failed,
    );
  });
});

describe('timeouts', () => {
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

  it('the login address and logout wait 8 s, the callback 30 s, as in Streamlit', async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      'fetch',
      vi.fn<Fetch>(
        (_url, init) =>
          new Promise<Response>((_answer, fail) =>
            init.signal?.addEventListener('abort', () =>
              fail(new DOMException('aborted', 'AbortError')),
            ),
          ),
      ),
    );
    try {
      await settlesAfter(startLogin('/', vi.fn()), 8_000);
      pending();
      await settlesAfter(finishLogin(`?code=c&state=${STATE}`), 30_000);
      await settlesAfter(logout(), 8_000);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('logging out', () => {
  it('asks the API, which alone can end an HttpOnly session', async () => {
    const fetch = serve(() => new Response(null, { status: 204 }));
    await expect(logout()).resolves.toBeUndefined();
    const [url, init] = fetch.mock.calls[0]!;
    expect(url).toBe('http://127.0.0.1:8000/auth/logout');
    expect(init).toMatchObject({ method: 'POST', credentials: 'include' });
    expect(init.headers).toEqual({ 'X-NEU-Compass': '1' });
    serve(() => json({ error_type: 'csrf_rejected' }, 403));
    await expect(logout()).rejects.toMatchObject({ status: 403 });
  });
});
