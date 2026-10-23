import {
  act,
  render,
  renderHook,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router-dom';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from '../App';
import { LOGIN_MESSAGES, PENDING_KEY } from '../api/login';
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
const notice = () =>
  screen.getAllByRole('status').find((node) => node.tagName === 'P')!;
const sidebar = () => screen.getByRole('complementary');
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

beforeEach(() => sessionStorage.clear());
afterEach(() => sessionStorage.clear());

describe('coming back from Google', () => {
  it('takes code and state out of the address, logs in and returns to the page', async () => {
    sessionStorage.setItem(
      PENDING_KEY,
      JSON.stringify({ state: STATE, returnTo: '/compare' }),
    );
    let answer: (response: Response) => void = () => {};
    const fetch = vi.fn<Fetch>(
      () => new Promise<Response>((resolve) => (answer = resolve)),
    );
    vi.stubGlobal('fetch', fetch);
    const client = page(`/?code=synthetic-code&state=${STATE}`);
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
    expect(screen.getAllByText('Synthetic Student').length).toBeGreaterThan(0);
    expect(fetch.mock.calls[0]![0]).toBe('http://127.0.0.1:8000/auth/callback');
    expect(sessionStorage.getItem(PENDING_KEY)).toBeNull();
    expect(screen.queryByText('游客')).not.toBeInTheDocument();
  });

  it('a wrong state is refused before anything is sent', async () => {
    sessionStorage.setItem(
      PENDING_KEY,
      JSON.stringify({ state: STATE, returnTo: '/coop' }),
    );
    page('/?code=synthetic-code&state=someone-elses-state-0123456789');
    await waitFor(() =>
      expect(notice()).toHaveTextContent('登录没有完成，请重新登录。'),
    );
    // React Router commits a navigation in a transition, after the notice.
    await waitFor(() => expect(where()).toHaveTextContent('/coop'));
  });

  it('Google’s cancel comes back as a line, not a login', async () => {
    page('/?error=access_denied&state=x');
    await waitFor(() =>
      expect(notice()).toHaveTextContent(
        '登录没有完成（access_denied），请再试一次。',
      ),
    );
    await waitFor(() => expect(where()).toHaveTextContent(/^\/$/));
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
      expect(notice()).toHaveTextContent(
        '只能用 husky.neu.edu 或 northeastern.edu 邮箱登录。',
      ),
    );
    expect(document.body).not.toHaveTextContent('Email domain not allowed');
    expect(client.getQueryData(meQuery.queryKey)).toEqual(GUEST);
  });

  it('an /auth/me asked before the login cannot turn the member back into a guest', async () => {
    sessionStorage.setItem(
      PENDING_KEY,
      JSON.stringify({ state: STATE, returnTo: '/' }),
    );
    const client = createQueryClient();
    client.setQueryData(configQuery.queryKey, {
      answer_feedback_enabled: false,
      login_available: true,
    });
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
        return Promise.resolve(json(identity));
      }),
    );
    page(`/?code=c&state=${STATE}`, client);
    await waitFor(() =>
      expect(client.getQueryData(meQuery.queryKey)).toEqual(MEMBER),
    );
    expect(meSignal?.aborted).toBe(true);
    late(json({ error_type: 'unauthorized' }, 401));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(client.getQueryData(meQuery.queryKey)).toEqual(MEMBER);
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
    page('/programs', client);
    addToCompare('c-cs-5800');
    await user.click(screen.getAllByRole('button', { name: '退出登录' })[0]!);
    await waitFor(() => expect(notice()).toHaveTextContent('已退出登录。'));
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
      expect(notice()).toHaveTextContent('没能退出登录，请再试一次。'),
    );
    expect(client.getQueryData(meQuery.queryKey)).toEqual(MEMBER);
    expect(getCompareList()).toEqual(['c-cs-5800']);
  });
});

describe('focus in the account box', () => {
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

  it('a keyboard logout leaves focus on the login button that replaces it', async () => {
    const calls = held();
    page('/', seededQueryClient({ viewer: MEMBER }));
    await pressAndDropFocus('退出登录', '正在退出…');
    calls[0]!.answer(new Response(null, { status: 204 }));
    await waitFor(() => expect(notice()).toHaveTextContent('已退出登录。'));
    expect(accountButton('用 NEU 邮箱登录')).toHaveFocus();
  });

  it('a logout that fails puts focus back on the logout button', async () => {
    const calls = held();
    page('/', seededQueryClient({ viewer: MEMBER }));
    await pressAndDropFocus('退出登录', '正在退出…');
    calls[0]!.fail(new TypeError('Failed to fetch'));
    await waitFor(() =>
      expect(notice()).toHaveTextContent('没能退出登录，请再试一次。'),
    );
    expect(accountButton('退出登录')).toHaveFocus();
  });

  it('a login start that fails puts focus back on the login button', async () => {
    const calls = held();
    page('/compare');
    await pressAndDropFocus('用 NEU 邮箱登录', '正在前往 Google…');
    calls[0]!.answer(json({ error_type: 'rate_limited' }, 429));
    await waitFor(() =>
      expect(notice()).toHaveTextContent('请求过于频繁，请稍后手动重试。'),
    );
    expect(accountButton('用 NEU 邮箱登录')).toHaveFocus();
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
    page('/', seededQueryClient({ viewer: MEMBER }));
    await pressAndDropFocus('退出登录', '正在退出…');
    const link = within(sidebar()).getByRole('link', { name: /培养方案/ });
    link.focus();
    calls[0]!.answer(new Response(null, { status: 204 }));
    await waitFor(() => expect(notice()).toHaveTextContent('已退出登录。'));
    expect(link).toHaveFocus();
  });
});

describe('the account box', () => {
  it('a member is named in the sidebar and has no guest badge', () => {
    page('/', seededQueryClient({ viewer: { ...MEMBER, displayName: null } }));
    expect(sidebar()).toHaveTextContent('synthetic.student@husky.neu.edu');
    expect(sidebar()).toHaveTextContent('贡献数：2');
    expect(screen.queryByText('游客')).not.toBeInTheDocument();
  });

  it('login is off when the API says so', () => {
    page(
      '/',
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
      expect(notice()).toHaveTextContent('请求过于频繁，请稍后手动重试。'),
    );
    expect(
      screen.getAllByRole('button', { name: '用 NEU 邮箱登录' })[0],
    ).toBeEnabled();
    expect(sessionStorage.getItem(PENDING_KEY)).toBeNull();
  });
});

describe('the hook', () => {
  function wrapper(client = seededQueryClient()) {
    return function Wrapper({ children }: { children: ReactNode }) {
      return (
        <WithApi client={client}>
          <MemoryRouter initialEntries={['/course/CS-6140?x=1']}>
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
    ).toMatchObject({ returnTo: '/course/CS-6140?x=1' });
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
