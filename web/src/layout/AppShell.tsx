import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useLayoutEffect, useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { refreshReads, shownData, useShowingOld } from '../api/queries';
import { ErrorBoundary } from '../components/ErrorBoundary';
import { coursesIndexed, readyQuery } from '../api/ready';
import { AccountContext, viewerOwner } from './account';
import { AskBar } from './AskBar';
import { MAIN_CONTENT, focusLost, focusMainContent } from './mainContent';
import { ProgramsProvider } from './ProgramsContext';
import { NEWEST_QUESTION, SearchProvider, useSearch } from './SearchContext';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';
import { pagePresentation } from './routePresentation';
import { useSession } from './useSession';
import { useCompareList } from '../models/compareList';
import styles from './AppShell.module.css';

// Streamlit's FALLBACK_NOTICE (app/streamlit_app.py), except its last clause: this page does not try again by itself.
export const FALLBACK_NOTICE =
  '有些内容这次没能更新，显示的是上次加载的版本；可以点「刷新页面内容」再试。';
// Pages that say who is looking themselves, so the top bar's guest badge would say it twice; their demos only where
// the demo pages are (R6).
const SAYS_WHO = new Set([
  '/coop',
  '/privacy',
  ...(__DEMO_ROUTES__ ? ['/coop-demo', '/privacy-demo'] : []),
]);

// The ask box asks in the shell's conversation; from a course page the answer is read on the search page, as R1's
// prototype did.
function SearchAskBar() {
  const search = useSearch();
  const { pathname } = useLocation();
  const navigate = useNavigate();
  return (
    <AskBar
      onSend={(question) => {
        search.ask(question);
        if (pathname !== '/') void navigate('/', { state: NEWEST_QUESTION });
      }}
    />
  );
}

export function AppShell() {
  const { pathname } = useLocation();
  const queryClient = useQueryClient();
  // What came back from Google, said at the top of the page. This shell's own: the offline demo shell keeps its note
  // to itself, so neither shows up in the other (review A32).
  const [notice, announce] = useState('');
  const comparison = useCompareList();
  const { session, login, logout, account, settled, note } =
    useSession(announce);
  // The top bar's course count, held back like /config while the address still carries Google's code (R3e).
  const ready = useQuery({ ...readyQuery, enabled: settled });
  const showingOld = useShowingOld();
  const box = { session, onLogin: login, onLogout: logout, note };
  const { title, isSearch, navigationPath } = pagePresentation(pathname);
  // A layout effect: a page that brings something into view when it opens (the search page's newest question, R6)
  // does so in an effect of its own, which runs after this one, so it is not scrolled back to the top.
  useLayoutEffect(() => {
    document.title = `${title} · NEU-Compass`;
    focusMainContent({ preventScroll: true });
    window.scrollTo({ top: 0, left: 0, behavior: 'instant' });
  }, [pathname, title]);
  // A page that failed to draw takes the ask box with it: what was asked there would go out, into the query log too,
  // with no page to show the answer (review A34). Focus that was on what went (a button of the page, the ask box) goes
  // to main, without scrolling.
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (failed && focusLost()) focusMainContent({ preventScroll: true });
  }, [failed]);
  const refresh = () => void refreshReads(queryClient);
  const owner =
    account.viewer === undefined ? undefined : viewerOwner(account.viewer);
  return (
    <div className={styles.shell}>
      {/* Not an in-page link: the browser would add a history entry with no state and the router would follow it, so a
          plan link being checked, a /?program= ref waiting for the list and a course page's course ID would be lost
          (R4c recheck A33 R2-1, R6). Focus moves to the main content, and the address and history stay. */}
      <a
        href={`#${MAIN_CONTENT}`}
        className="skip-link"
        onClick={(event) => {
          // A click with a modifier is the browser's (a new tab or window), as on the router's links (review A34).
          if (
            event.button !== 0 ||
            event.metaKey ||
            event.altKey ||
            event.ctrlKey ||
            event.shiftKey
          )
            return;
          event.preventDefault();
          focusMainContent();
        }}
      >
        跳到主要内容
      </a>
      <aside className={styles.desktopSidebar}>
        <Sidebar
          compareCount={comparison.length}
          onRefresh={refresh}
          {...box}
        />
      </aside>
      <div className={styles.mainColumn}>
        <TopBar
          showGuest={
            session.kind === 'guest' &&
            !(navigationPath !== undefined && SAYS_WHO.has(navigationPath))
          }
          title={title}
          count={comparison.length}
          courses={coursesIndexed(shownData(ready))}
          onRefresh={refresh}
          account={box}
        />
        <AccountContext.Provider value={account}>
          <SearchProvider owner={owner}>
            <ProgramsProvider owner={owner}>
              <main id={MAIN_CONTENT} tabIndex={-1} className={styles.main}>
                <div
                  role="status"
                  aria-label="内容更新"
                  className={styles.fallback}
                >
                  {showingOld && <p>{FALLBACK_NOTICE}</p>}
                </div>
                {/* What came back from Google, at the top where the page opens (R3e). */}
                <p
                  role="status"
                  aria-label="登录结果"
                  className={styles.returnNote}
                >
                  {notice}
                </p>
                <ErrorBoundary where={pathname} onFailed={setFailed}>
                  <Outlet />
                </ErrorBoundary>
              </main>
              {isSearch && !failed && <SearchAskBar />}
            </ProgramsProvider>
          </SearchProvider>
        </AccountContext.Provider>
      </div>
    </div>
  );
}
