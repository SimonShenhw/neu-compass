import {
  act,
  render,
  renderHook,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BrowserRouter, MemoryRouter, useLocation } from 'react-router-dom';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from '../App';
import { LOGIN_MESSAGES, PENDING_KEY } from '../api/login';
import { programListQuery } from '../api/programs';
import { GUEST, configQuery, createQueryClient, meQuery } from '../api/queries';
import type { Member } from '../api/queries';
import { addToCompare, getCompareList } from '../models/compareList';
import { WithApi, seededQueryClient } from '../test/withApi';
import { Sidebar } from './Sidebar';
import type { SessionView } from './Sidebar';
import { VIEWER_KEY, useSession } from './useSession';

type Fetch = (url: string, init: RequestInit) => Promise<Response>;
const STATE = 'synthetic-state-0123456789abcdefghijklmnopq';
const MEMBER: Member = {
  kind: 'member',
  userId: 'u-1',
  email: 'synthetic.student@husky.neu.edu',
  displayName: 'Synthetic Student',
  contributionCount: 2,
};
const identity = {
  user_id: 'u-1',
  email: 'synthetic.student@husky.neu.edu',
  display_name: 'Synthetic Student',
  contribution_count: 2,
  session_token: null,
};
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status });

function Where() {
  const { pathname, search } = useLocation();
  return <output aria-label="where">{`${pathname}${search}`}</output>;
}
function page(path: string, client = seededQueryClient()) {
  render(
    <WithApi client={client}>
      <MemoryRouter initialEntries={[path]}>
        <App />
        <Where />
      </MemoryRouter>
    </WithApi>,
  );
  return client;
}
const where = () => screen.getByRole('status', { name: 'where' });
const sidebar = () => screen.getByRole('complementary');
// What a press in the account box came to, said in the box (R3e).
const boxNote = () => within(sidebar()).getByRole('status');
// What came back from Google, at the top of the page (R3e).
const returnNote = () => screen.getByRole('status', { name: '登录结果' });
const accountButton = (name: string) =>
  within(sidebar()).getByRole('button', { name });
// Browsers move focus to the page when the focused button is disabled; jsdom leaves it on the button (and will not
// blur a disabled one), so the tests move it the same way.
async function pressAndDropFocus(name: string, busyName: string) {
  accountButton(name).focus();
  await userEvent.keyboard('{Enter}');
  await waitFor(() => expect(accountButton(busyName)).toBeDisabled());
  document.body.tabIndex = -1;
  document.body.focus();
  document.body.removeAttribute('tabindex');
  expect(document.body).toHaveFocus();
}
// Where focus is at the moment a text first appears in the page. The button must have it back by then, in the same
// commit as the result, not a moment later: a later move is what made two focus tests flaky (B26).
function focusWhenShown(text: string) {
  const seen: { focus?: Element | null } = {};
  const observer = new MutationObserver(() => {
    if (!('focus' in seen) && document.body.textContent?.includes(text)) {
      seen.focus = document.activeElement;
      observer.disconnect();
    }
  });
  observer.observe(document.body, {
    childList: true,
    subtree: true,
    characterData: true,
  });
  return seen;
}

beforeEach(() => sessionStorage.clear());
afterEach(() => {
  sessionStorage.clear();
  window.history.replaceState(null, '', '/');
});

// Every request answered by its path; held ones wait until the test answers them.
function held() {
  const calls: {
    answer: (response: Response) => void;
    fail: (error: unknown) => void;
  }[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn<Fetch>(
      () =>
        new Promise<Response>((answer, fail) => calls.push({ answer, fail })),
    ),
  );
  return calls;
}
const pendingLogin = (returnTo: string) =>
  sessionStorage.setItem(
    PENDING_KEY,
    JSON.stringify({ state: STATE, returnTo }),
  );
// The address bar as the browser shows it (BrowserRouter writes it at once; MemoryRouter never does).
const addressBar = () =>
  `${window.location.pathname}${window.location.search}${window.location.hash}`;

describe('coming back from Google', () => {
  it('takes code and state out of the address, logs in and returns to the page', async () => {
    pendingLogin('/compare');
    let answer: (response: Response) => void = () => {};
    const fetch = vi.fn<Fetch>((url) =>
      url.endsWith('/auth/callback')
        ? new Promise<Response>((resolve) => (answer = resolve))
        : Promise.resolve(json(identity)),
    );
    vi.stubGlobal('fetch', fetch);
    const client = seededQueryClient();
    client.setQueryData([...VIEWER_KEY, 'u-0', 'coop'], ['the last viewer’s']);
    page(`/?code=synthetic-code&state=${STATE}`, client);
    // Before the API has answered, the address no longer carries them.
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    expect(where()).toHaveTextContent(/^\/$/);
    expect(screen.getAllByText('正在确认登录状态…').length).toBeGreaterThan(0);
    answer(json(identity));
    await waitFor(() => expect(where()).toHaveTextContent('/compare'));
    // Handled once: arriving at the page does not run the return again (its state is used up by now).
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(where()).toHaveTextContent('/compare');
    expect(screen.queryByText(LOGIN_MESSAGES.forged)).not.toBeInTheDocument();
    expect(client.getQueryData(meQuery.queryKey)).toEqual(MEMBER);
    expect(client.getQueryData([...VIEWER_KEY, 'u-0', 'coop'])).toBeUndefined();
    expect(screen.getAllByText('Synthetic Student').length).toBeGreaterThan(0);
    // The callback, then /auth/me read again; nothing else.
    expect(fetch.mock.calls.map(([url]) => url)).toEqual([
      'http://127.0.0.1:8000/auth/callback',
      'http://127.0.0.1:8000/auth/me',
    ]);
    expect(sessionStorage.getItem(PENDING_KEY)).toBeNull();
    expect(screen.queryByText('游客')).not.toBeInTheDocument();
  });

  it('nothing is asked while the address carries the code, and it never stays in the history', async () => {
    pendingLogin('/compare');
    const sent: string[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn<Fetch>(async (url) => {
        sent.push(`${new URL(url).pathname} from ${addressBar()}`);
        return url.endsWith('/config')
          ? json({ answer_feedback_enabled: false, login_available: true })
          : json(identity);
      }),
    );
    window.history.replaceState(
      null,
      '',
      `/?code=synthetic-code&state=${STATE}`,
    );
    const length = window.history.length;
    render(
      <WithApi client={createQueryClient()}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </WithApi>,
    );
    await waitFor(() => expect(sent).toHaveLength(4));
    expect(sent).toEqual([
      '/auth/callback from /',
      '/auth/me from /',
      '/config from /compare',
      '/ready from /compare',
    ]);
    expect(addressBar()).toBe('/compare');
    // Both steps replaced the entry: going back cannot reach an address with the code in it.
    expect(window.history.length).toBe(length);
  });

  it('a browser that did not keep the cookie is told so, and the student stays a guest', async () => {
    pendingLogin('/compare');
    vi.stubGlobal(
      'fetch',
      vi.fn<Fetch>(async (url) =>
        url.endsWith('/auth/callback')
          ? json(identity)
          : json({ error_type: 'unauthorized' }, 401),
      ),
    );
    const client = page(`/?code=c&state=${STATE}`);
    await waitFor(() =>
      expect(returnNote()).toHaveTextContent(LOGIN_MESSAGES.notKept),
    );
    await waitFor(() => expect(where()).toHaveTextContent('/compare'));
    expect(client.getQueryData(meQuery.queryKey)).toEqual(GUEST);
    expect(accountButton('用 NEU 邮箱登录')).toBeEnabled();
  });

  it.each([
    [
      'fails for a moment (503)',
      async () => json({ error_type: 'service_unavailable' }, 503),
    ],
    [
      'gets a definite error (404)',
      async () => json({ error_type: 'not_found' }, 404),
    ],
    [
      'loses the connection',
      () => Promise.reject(new TypeError('Failed to fetch')),
    ],
  ])(
    'an /auth/me that %s after the login leaves the member shown and is not sent again by itself',
    async (_, reread: () => Promise<Response>) => {
      pendingLogin('/compare');
      const fetch = vi.fn<Fetch>(async (url) =>
        url.endsWith('/auth/callback') ? json(identity) : reread(),
      );
      vi.stubGlobal('fetch', fetch);
      const client = page(`/?code=c&state=${STATE}`);
      await waitFor(() => expect(where()).toHaveTextContent('/compare'));
      expect(
        within(sidebar()).getByText('Synthetic Student'),
      ).toBeInTheDocument();
      expect(
        screen.queryByText(LOGIN_MESSAGES.notKept),
      ).not.toBeInTheDocument();
      // The failed read is not left in the cache: an error there would mark the query for a refetch of its own.
      expect(client.getQueryState(meQuery.queryKey)).toMatchObject({
        status: 'success',
        isInvalidated: false,
      });
      expect(client.getQueryData(meQuery.queryKey)).toEqual(MEMBER);
      expect(
        fetch.mock.calls.filter(([url]) => url.endsWith('/auth/me')),
      ).toHaveLength(1);
    },
  );

  it('a wrong state is refused before anything is sent', async () => {
    // A page that asks for nothing by itself (an empty comparison), so any request would be the login's.
    pendingLogin('/compare');
    const fetch = vi.fn<Fetch>();
    vi.stubGlobal('fetch', fetch);
    page('/?code=synthetic-code&state=someone-elses-state-0123456789');
    await waitFor(() =>
      expect(returnNote()).toHaveTextContent('登录没有完成，请重新登录。'),
    );
    // React Router commits a navigation in a transition, after the notice.
    await waitFor(() => expect(where()).toHaveTextContent('/compare'));
    expect(fetch).not.toHaveBeenCalled();
    // At the top of the page, right under the line on content shown from before; not in the account box.
    expect([...screen.getByRole('main').children].indexOf(returnNote())).toBe(
      1,
    );
    expect(boxNote()).toBeEmptyDOMElement();
  });

  it('Google’s cancel comes back as a line, not a login', async () => {
    // Back to a page that asks for nothing by itself (an empty comparison): the search page asks for what it shows.
    pendingLogin('/compare');
    page(`/?error=access_denied&state=${STATE}`);
    await waitFor(() =>
      expect(returnNote()).toHaveTextContent(
        '登录没有完成（access_denied），请再试一次。',
      ),
    );
    await waitFor(() => expect(where()).toHaveTextContent('/compare'));
    expect(sessionStorage.getItem(PENDING_KEY)).toBeNull();
  });

  it('a refused domain is said in Chinese, and the student stays a guest', async () => {
    sessionStorage.setItem(
      PENDING_KEY,
      JSON.stringify({ state: STATE, returnTo: '/' }),
    );
    vi.stubGlobal(
      'fetch',
      vi.fn<Fetch>(async () =>
        json(
          {
            detail: 'Email domain not allowed.',
            error_type: 'unauthorized',
            reason: 'domain_not_allowed',
          },
          401,
        ),
      ),
    );
    const client = page(`/?code=c&state=${STATE}`);
    await waitFor(() =>
      expect(returnNote()).toHaveTextContent(
        '只能用 husky.neu.edu 或 northeastern.edu 邮箱登录。',
      ),
    );
    expect(document.body).not.toHaveTextContent('Email domain not allowed');
    expect(client.getQueryData(meQuery.queryKey)).toEqual(GUEST);
  });
});

describe('logging out', () => {
  it('asks the API, then forgets the viewer’s data and the comparison', async () => {
    const user = userEvent.setup();
    const fetch = vi.fn<Fetch>(async () => new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', fetch);
    const client = seededQueryClient({ viewer: MEMBER });
    client.setQueryData([...VIEWER_KEY, 'u-1', 'coop'], ['private']);
    client.setQueryData(['course', 'c-cs-5800'], { public: true });
    // The program list is there already, so the page asks for nothing before the logout (R4c).
    client.setQueryData(programListQuery.queryKey, []);
    page('/programs', client);
    addToCompare('c-cs-5800');
    await user.click(screen.getAllByRole('button', { name: '退出登录' })[0]!);
    await waitFor(() => expect(boxNote()).toHaveTextContent('已退出登录。'));
    expect(fetch.mock.calls[0]![0]).toBe('http://127.0.0.1:8000/auth/logout');
    expect(client.getQueryData(meQuery.queryKey)).toEqual(GUEST);
    expect(client.getQueryData([...VIEWER_KEY, 'u-1', 'coop'])).toBeUndefined();
    expect(client.getQueryData(['course', 'c-cs-5800'])).toEqual({
      public: true,
    });
    expect(getCompareList()).toEqual([]);
    expect(where()).toHaveTextContent('/programs');
    expect(
      screen.getAllByRole('button', { name: '用 NEU 邮箱登录' }).length,
    ).toBeGreaterThan(0);
  });

  it('a logout that fails does not pretend', async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      'fetch',
      vi.fn<Fetch>(async () => {
        throw new TypeError('Failed to fetch');
      }),
    );
    const client = seededQueryClient({ viewer: MEMBER });
    page('/', client);
    addToCompare('c-cs-5800');
    await user.click(screen.getAllByRole('button', { name: '退出登录' })[0]!);
    await waitFor(() =>
      expect(boxNote()).toHaveTextContent('没能退出登录，请再试一次。'),
    );
    expect(client.getQueryData(meQuery.queryKey)).toEqual(MEMBER);
    expect(getCompareList()).toEqual(['c-cs-5800']);
  });

  it('an /auth/me still on its way at logout cannot bring the member back', async () => {
    const user = userEvent.setup();
    let late: (response: Response) => void = () => {};
    let meSignal: AbortSignal | undefined;
    vi.stubGlobal(
      'fetch',
      vi.fn<Fetch>((url, init) => {
        if (url.endsWith('/auth/me')) {
          meSignal = init.signal ?? undefined;
          return new Promise<Response>((resolve, reject) => {
            late = resolve;
            meSignal?.addEventListener('abort', () => reject(meSignal?.reason));
          });
        }
        return Promise.resolve(new Response(null, { status: 204 }));
      }),
    );
    const client = seededQueryClient({ viewer: MEMBER });
    page('/', client);
    void client.refetchQueries({ queryKey: meQuery.queryKey });
    await waitFor(() => expect(meSignal).toBeDefined());
    await user.click(accountButton('退出登录'));
    await waitFor(() => expect(boxNote()).toHaveTextContent('已退出登录。'));
    expect(meSignal?.aborted).toBe(true);
    late(json(identity));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(client.getQueryData(meQuery.queryKey)).toEqual(GUEST);
  });
});

describe('the mobile menu', () => {
  async function openMenu() {
    await userEvent.click(screen.getByRole('button', { name: '打开导航菜单' }));
    return screen.getByRole('dialog');
  }

  it('has the same account box as the sidebar', async () => {
    page('/compare', seededQueryClient({ viewer: MEMBER }));
    const menu = await openMenu();
    expect(menu).toHaveTextContent('Synthetic Student');
    expect(menu).toHaveTextContent('贡献数：2');
    expect(
      within(menu).getByRole('button', { name: '退出登录' }),
    ).toBeEnabled();
  });

  it('a logout in the menu is said in the menu, and leaves focus on its login button', async () => {
    const calls = held();
    page('/compare', seededQueryClient({ viewer: MEMBER }));
    const menu = await openMenu();
    within(menu).getByRole('button', { name: '退出登录' }).focus();
    await userEvent.keyboard('{Enter}');
    await waitFor(() =>
      expect(
        within(menu).getByRole('button', { name: '正在退出…' }),
      ).toBeDisabled(),
    );
    // A browser moves focus off the disabled button to the menu around it.
    menu.focus();
    expect(menu).toHaveFocus();
    calls[0]!.answer(new Response(null, { status: 204 }));
    const login = await within(menu).findByRole('button', {
      name: '用 NEU 邮箱登录',
    });
    expect(login).toHaveFocus();
    // The page behind an open menu is hidden from a screen reader; the menu's own box says it.
    expect(within(menu).getByRole('status')).toHaveTextContent('已退出登录。');
  });
});

describe('focus in the account box', () => {
  it('a keyboard logout leaves focus on the login button that replaces it', async () => {
    const calls = held();
    page('/compare', seededQueryClient({ viewer: MEMBER }));
    await pressAndDropFocus('退出登录', '正在退出…');
    calls[0]!.answer(new Response(null, { status: 204 }));
    await waitFor(() => expect(boxNote()).toHaveTextContent('已退出登录。'));
    expect(accountButton('用 NEU 邮箱登录')).toHaveFocus();
  });

  it('a logout that fails puts focus back on the logout button', async () => {
    const calls = held();
    page('/compare', seededQueryClient({ viewer: MEMBER }));
    await pressAndDropFocus('退出登录', '正在退出…');
    const shown = focusWhenShown('没能退出登录，请再试一次。');
    calls[0]!.fail(new TypeError('Failed to fetch'));
    await waitFor(() =>
      expect(boxNote()).toHaveTextContent('没能退出登录，请再试一次。'),
    );
    expect(accountButton('退出登录')).toHaveFocus();
    expect(shown.focus).toBe(accountButton('退出登录'));
  });

  it('a login start that fails puts focus back on the login button', async () => {
    const calls = held();
    page('/compare');
    await pressAndDropFocus('用 NEU 邮箱登录', '正在前往 Google…');
    const shown = focusWhenShown('请求过于频繁，请稍后手动重试。');
    calls[0]!.answer(json({ error_type: 'rate_limited' }, 429));
    await waitFor(() =>
      expect(boxNote()).toHaveTextContent('请求过于频繁，请稍后手动重试。'),
    );
    expect(accountButton('用 NEU 邮箱登录')).toHaveFocus();
    expect(shown.focus).toBe(accountButton('用 NEU 邮箱登录'));
  });

  it('a box that was not pressed leaves focus alone', () => {
    const box = (session: SessionView) => (
      <MemoryRouter>
        <Sidebar session={session} />
      </MemoryRouter>
    );
    const { rerender } = render(
      box({
        kind: 'signed-in',
        displayName: 'Synthetic Student',
        contributionCount: 2,
        busy: true,
      }),
    );
    rerender(box({ kind: 'guest', login: 'ready' }));
    expect(document.body).toHaveFocus();
  });

  it('focus the student moved elsewhere meanwhile stays there', async () => {
    const calls = held();
    page('/compare', seededQueryClient({ viewer: MEMBER }));
    await pressAndDropFocus('退出登录', '正在退出…');
    const link = within(sidebar()).getByRole('link', { name: /培养方案/ });
    link.focus();
    calls[0]!.answer(new Response(null, { status: 204 }));
    await waitFor(() => expect(boxNote()).toHaveTextContent('已退出登录。'));
    expect(link).toHaveFocus();
  });
});

describe('the account box', () => {
  it('a member is named in the sidebar and has no guest badge', () => {
    page(
      '/compare',
      seededQueryClient({ viewer: { ...MEMBER, displayName: null } }),
    );
    expect(sidebar()).toHaveTextContent('synthetic.student@husky.neu.edu');
    expect(sidebar()).toHaveTextContent('贡献数：2');
    expect(screen.queryByText('游客')).not.toBeInTheDocument();
  });

  it('login is off when the API says so', () => {
    page(
      '/compare',
      seededQueryClient({
        config: { answer_feedback_enabled: false, login_available: false },
      }),
    );
    expect(
      screen.getAllByRole('button', { name: '用 NEU 邮箱登录' })[0],
    ).toBeDisabled();
    expect(sidebar()).toHaveTextContent('暂时不能登录。');
    expect(screen.getByText('游客')).toBeInTheDocument();
  });

  it('a failed login start is said and the button comes back', async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      'fetch',
      vi.fn<Fetch>(async () => json({ error_type: 'rate_limited' }, 429)),
    );
    page('/compare');
    await user.click(
      screen.getAllByRole('button', { name: '用 NEU 邮箱登录' })[0]!,
    );
    await waitFor(() =>
      expect(boxNote()).toHaveTextContent('请求过于频繁，请稍后手动重试。'),
    );
    expect(
      screen.getAllByRole('button', { name: '用 NEU 邮箱登录' })[0],
    ).toBeEnabled();
    expect(sessionStorage.getItem(PENDING_KEY)).toBeNull();
  });

  it('a second press clears what the first came to, so the same words are said again', async () => {
    const calls = held();
    page('/compare');
    await userEvent.click(accountButton('用 NEU 邮箱登录'));
    calls[0]!.answer(json({ error_type: 'rate_limited' }, 429));
    await waitFor(() =>
      expect(boxNote()).toHaveTextContent('请求过于频繁，请稍后手动重试。'),
    );
    await userEvent.click(accountButton('用 NEU 邮箱登录'));
    expect(boxNote()).toBeEmptyDOMElement();
    calls[1]!.answer(json({ error_type: 'rate_limited' }, 429));
    await waitFor(() =>
      expect(boxNote()).toHaveTextContent('请求过于频繁，请稍后手动重试。'),
    );
    expect(returnNote()).toBeEmptyDOMElement();
  });

  it('so does a second logout press (review B32)', async () => {
    const calls = held();
    page('/compare', seededQueryClient({ viewer: MEMBER }));
    await userEvent.click(accountButton('退出登录'));
    calls[0]!.fail(new TypeError('Failed to fetch'));
    await waitFor(() =>
      expect(boxNote()).toHaveTextContent('没能退出登录，请再试一次。'),
    );
    // Shown, not only said: the line is hidden only while it is empty (review B32).
    expect(boxNote()).not.toHaveClass('visually-hidden');
    await userEvent.click(accountButton('退出登录'));
    expect(boxNote()).toBeEmptyDOMElement();
    expect(boxNote()).toHaveClass('visually-hidden');
    calls[1]!.answer(new Response(null, { status: 204 }));
    await waitFor(() => expect(boxNote()).toHaveTextContent('已退出登录。'));
  });
});

describe('the hook', () => {
  function wrapper(client = seededQueryClient()) {
    return function Wrapper({ children }: { children: ReactNode }) {
      return (
        <WithApi client={client}>
          <MemoryRouter initialEntries={['/course/CS-6140?x=1#evidence']}>
            {children}
          </MemoryRouter>
        </WithApi>
      );
    };
  }

  it('a login goes to Google with the page to come back to, and only once', async () => {
    const fetch = vi.fn<Fetch>(async () =>
      json({ url: 'https://accounts.google.com/o/oauth2/v2/auth?x=1' }),
    );
    vi.stubGlobal('fetch', fetch);
    const go = vi.fn();
    const { result } = renderHook(() => useSession(vi.fn(), go), {
      wrapper: wrapper(),
    });
    result.current.login();
    await waitFor(() => expect(go).toHaveBeenCalledTimes(1));
    expect(go).toHaveBeenCalledWith(
      'https://accounts.google.com/o/oauth2/v2/auth?x=1',
    );
    expect(result.current.session).toEqual({
      kind: 'guest',
      login: 'busy',
      unsure: false,
    });
    result.current.login();
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(
      JSON.parse(sessionStorage.getItem(PENDING_KEY)!) as { returnTo: string },
    ).toMatchObject({ returnTo: '/course/CS-6140?x=1#evidence' });
  });

  it('a second logout while one is on its way sends nothing', async () => {
    const fetch = vi.fn<Fetch>(() => new Promise<Response>(() => {}));
    vi.stubGlobal('fetch', fetch);
    const { result } = renderHook(() => useSession(vi.fn(), vi.fn()), {
      wrapper: wrapper(seededQueryClient({ viewer: MEMBER })),
    });
    act(() => result.current.logout());
    await waitFor(() =>
      expect(result.current.session).toMatchObject({ busy: true }),
    );
    act(() => result.current.logout());
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('a page the browser brings back from its cache can log in again', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn<Fetch>(async () =>
        json({ url: 'https://accounts.google.com/o/oauth2/v2/auth?x=1' }),
      ),
    );
    const go = vi.fn();
    const { result } = renderHook(() => useSession(vi.fn(), go), {
      wrapper: wrapper(),
    });
    result.current.login();
    await waitFor(() => expect(go).toHaveBeenCalledTimes(1));
    const show = (persisted: boolean) =>
      act(() => {
        window.dispatchEvent(
          new PageTransitionEvent('pageshow', { persisted }),
        );
      });
    // A page loaded afresh is not the one that left.
    show(false);
    expect(result.current.session).toMatchObject({ login: 'busy' });
    show(true);
    expect(result.current.session).toMatchObject({ login: 'ready' });
  });

  it('a guest whose /auth/me failed is shown as unsure', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn<Fetch>(async () => json({}, 503)),
    );
    const client = createQueryClient();
    client.setQueryData(configQuery.queryKey, {
      answer_feedback_enabled: false,
      login_available: true,
    });
    const { result } = renderHook(() => useSession(vi.fn(), vi.fn()), {
      wrapper: wrapper(client),
    });
    expect(result.current.session).toEqual({ kind: 'checking' });
    await waitFor(() =>
      expect(result.current.session).toEqual({
        kind: 'guest',
        login: 'ready',
        unsure: true,
      }),
    );
  });
});

describe('the account the pages get (R5d)', () => {
  function at(path: string, client = seededQueryClient()) {
    return function Wrapper({ children }: { children: ReactNode }) {
      return (
        <WithApi client={client}>
          <MemoryRouter initialEntries={[path]}>{children}</MemoryRouter>
        </WithApi>
      );
    };
  }

  it('is the account box’s viewer', () => {
    const { result } = renderHook(() => useSession(vi.fn(), vi.fn()), {
      wrapper: at('/', seededQueryClient({ viewer: MEMBER })),
    });
    expect(result.current.account).toMatchObject({
      viewer: MEMBER,
      unsure: false,
    });
    expect(result.current.account.login).toBe(result.current.login);
  });

  it('knows nobody while the address still carries Google’s code', () => {
    pendingLogin('/');
    vi.stubGlobal(
      'fetch',
      vi.fn<Fetch>(() => new Promise<Response>(() => {})),
    );
    const { result } = renderHook(() => useSession(vi.fn(), vi.fn()), {
      wrapper: at(
        `/?code=synthetic-code&state=${STATE}`,
        seededQueryClient({ viewer: MEMBER }),
      ),
    });
    expect(result.current.session).toEqual({ kind: 'checking' });
    expect(result.current.account).toMatchObject({
      viewer: undefined,
      unsure: false,
    });
  });

  it('knows nobody, not even as unsure, while the address carries Google’s code after /auth/me had failed', () => {
    pendingLogin('/');
    vi.stubGlobal(
      'fetch',
      vi.fn<Fetch>(() => new Promise<Response>(() => {})),
    );
    const client = seededQueryClient();
    const me = client.getQueryCache().find({ queryKey: meQuery.queryKey })!;
    me.setState({
      ...me.state,
      status: 'error',
      data: undefined,
      error: new Error('API 503'),
    });
    const { result } = renderHook(() => useSession(vi.fn(), vi.fn()), {
      wrapper: at(`/?code=synthetic-code&state=${STATE}`, client),
    });
    expect(result.current.account).toMatchObject({
      viewer: undefined,
      unsure: false,
    });
  });

  it('a new count from the server goes in as a change of viewer; the same count, or a guest, changes nothing', async () => {
    const client = seededQueryClient({ viewer: MEMBER });
    const kept = ['viewer', 'member:u-1:2', 'coop'];
    client.setQueryData(kept, []);
    const { result } = renderHook(() => useSession(vi.fn(), vi.fn()), {
      wrapper: at('/', client),
    });
    await act(() => result.current.account.contributed(2));
    expect(client.getQueryData(kept)).toEqual([]);
    await act(() => result.current.account.contributed(3));
    expect(client.getQueryData(meQuery.queryKey)).toEqual({
      ...MEMBER,
      contributionCount: 3,
    });
    expect(client.getQueryData(kept)).toBeUndefined();
    await waitFor(() =>
      expect(result.current.session).toMatchObject({ contributionCount: 3 }),
    );
    const guest = seededQueryClient();
    const { result: asGuest } = renderHook(() => useSession(vi.fn(), vi.fn()), {
      wrapper: at('/', guest),
    });
    await act(() => asGuest.current.account.contributed(3));
    expect(guest.getQueryData(meQuery.queryKey)).toEqual(GUEST);
  });

  it('signedOut forgets the viewer, the comparison and what was kept for them, and sends nothing', async () => {
    const fetch = vi.fn<Fetch>();
    vi.stubGlobal('fetch', fetch);
    const client = seededQueryClient({ viewer: MEMBER });
    client.setQueryData([...VIEWER_KEY, 'member:u-1:2', 'coop'], []);
    addToCompare('c-cs-5800');
    const announce = vi.fn();
    const { result } = renderHook(() => useSession(announce, vi.fn()), {
      wrapper: at('/', client),
    });
    await act(() => result.current.account.signedOut());
    expect(client.getQueryData(meQuery.queryKey)).toEqual(GUEST);
    expect(client.getQueriesData({ queryKey: VIEWER_KEY })).toEqual([]);
    expect(getCompareList()).toEqual([]);
    await waitFor(() =>
      expect(result.current.session).toMatchObject({ kind: 'guest' }),
    );
    expect(fetch).not.toHaveBeenCalled();
    expect(announce).not.toHaveBeenCalled();
  });
});
