// Who is looking, and the login and logout buttons (R2b). AppShell uses this once and hands the result to the
// desktop sidebar and the mobile menu.
import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  LOGIN_MESSAGES,
  finishLogin,
  isLoginReturn,
  loginFailureMessage,
  logout,
  startLogin,
} from '../api/login';
import { GUEST, meQuery, shownData, useConfig, useMe } from '../api/queries';
import type { Viewer } from '../api/queries';
import { clearCompare } from '../models/compareList';
import type { SessionView } from './Sidebar';

// The first key of every query whose answer depends on who is asking (R5d's Co-op list and the like): dropped at
// login and logout, so nobody sees what the last person saw (R0 14.9).
export const VIEWER_KEY = ['viewer'] as const;

export function useSession(
  announce: (message: string) => void,
  // Leaving the page for Google; a test passes a spy.
  go: (url: string) => void = (url) => window.location.assign(url),
) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  // The address the page was loaded with: a return from Google is handled once, on that address only.
  const loaded = useRef(location);
  const [busy, setBusy] = useState<'returning' | 'login' | 'logout' | null>(
    () =>
      isLoginReturn(location.pathname, location.search) ? 'returning' : null,
  );
  // While the address still carries Google's code, neither /config nor /auth/me is asked: an /auth/me sent with an
  // old cookie could answer after the login and expire the new cookie.
  const config = useConfig(busy !== 'returning');
  const me = useMe(busy !== 'returning');
  const handled = useRef(false);

  const becomes = useCallback(
    async (viewer: Viewer) => {
      // A /auth/me still on its way was asked before the change; its answer must not overwrite the new viewer.
      await queryClient.cancelQueries({ queryKey: meQuery.queryKey });
      queryClient.removeQueries({ queryKey: VIEWER_KEY });
      queryClient.setQueryData(meQuery.queryKey, viewer);
    },
    [queryClient],
  );

  // After the callback, /auth/me is read again (plan 3.1): only that shows the browser kept the cookie. A browser that
  // refused it answers as a guest; a read that fails for a moment leaves the callback's answer standing.
  const kept = useCallback(async () => {
    try {
      const viewer = await queryClient.fetchQuery({ ...meQuery, staleTime: 0 });
      return viewer.kind === 'member';
    } catch {
      return true;
    }
  }, [queryClient]);

  useEffect(() => {
    if (handled.current) return;
    handled.current = true;
    const { pathname, search } = loaded.current;
    if (!isLoginReturn(pathname, search)) return;
    // First take code and state out of the address bar and the history, so no link or reload carries them.
    void navigate('/', { replace: true });
    void finishLogin(search).then(async (result) => {
      if (result.kind === 'done') {
        await becomes(result.member);
        if (!(await kept())) announce(LOGIN_MESSAGES.notKept);
      }
      if (result.kind === 'failed') announce(result.message);
      if (result.kind !== 'none')
        void navigate(result.returnTo, { replace: true });
      setBusy(null);
    });
  }, [announce, becomes, kept, navigate]);

  useEffect(() => {
    // Back from Google's page, the browser may show this page as it was left (the back-forward cache), still on its
    // way to Google; the login button must work again.
    const restored = (event: PageTransitionEvent) => {
      if (event.persisted) setBusy(null);
    };
    window.addEventListener('pageshow', restored);
    return () => window.removeEventListener('pageshow', restored);
  }, []);

  const login = useCallback(() => {
    if (busy) return;
    setBusy('login');
    startLogin(`${location.pathname}${location.search}${location.hash}`, go)
      // On success the page is leaving for Google; only a failure comes back here.
      .catch((error: unknown) => {
        announce(loginFailureMessage(error));
        setBusy(null);
      });
  }, [announce, busy, go, location]);

  const signOut = useCallback(() => {
    if (busy) return;
    setBusy('logout');
    logout()
      .then(
        async () => {
          await becomes(GUEST);
          clearCompare();
          announce(LOGIN_MESSAGES.loggedOut);
        },
        // The cookie is HttpOnly: without the API's answer the session may still be alive, so say so.
        () => announce(LOGIN_MESSAGES.logoutFailed),
      )
      .finally(() => setBusy(null));
  }, [announce, becomes, busy]);

  const viewer = shownData(me);
  const loginState = shownData(config)?.login_available
    ? 'ready'
    : config.isPending
      ? 'checking'
      : 'unavailable';
  const session: SessionView =
    busy === 'returning' || (viewer === undefined && me.isPending)
      ? { kind: 'checking' }
      : viewer?.kind === 'member'
        ? {
            kind: 'signed-in',
            displayName: viewer.displayName || viewer.email,
            contributionCount: viewer.contributionCount,
            busy: busy === 'logout',
          }
        : {
            kind: 'guest',
            login: busy === 'login' ? 'busy' : loginState,
            unsure: viewer === undefined && me.isError,
          };
  return { session, login, logout: signOut };
}
