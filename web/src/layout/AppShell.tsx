import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { refreshReads, shownData, useShowingOld } from '../api/queries';
import { coursesIndexed, readyQuery } from '../api/ready';
import { AccountContext, viewerOwner } from './account';
import { AskBar } from './AskBar';
import { ProgramsProvider } from './ProgramsContext';
import { SearchProvider, useSearch } from './SearchContext';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';
import { pagePresentation } from './routePresentation';
import { useSession } from './useSession';
import { useCompareList } from '../models/compareList';
import styles from './AppShell.module.css';

// Streamlit's FALLBACK_NOTICE (app/streamlit_app.py), except its last clause: this page does not try again by itself.
export const FALLBACK_NOTICE =
  '有些内容这次没能更新，显示的是上次加载的版本；可以点「刷新页面内容」再试。';
// Pages that say who is looking themselves, so the top bar's guest badge would say it twice.
const SAYS_WHO = new Set(['/coop', '/privacy', '/coop-demo', '/privacy-demo']);

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
        if (pathname !== '/') void navigate('/');
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
  useEffect(() => {
    document.title = `${title} · NEU-Compass`;
    document.getElementById('main-content')?.focus({ preventScroll: true });
    window.scrollTo({ top: 0, left: 0, behavior: 'instant' });
  }, [pathname, title]);
  const refresh = () => void refreshReads(queryClient);
  const owner =
    account.viewer === undefined ? undefined : viewerOwner(account.viewer);
  return (
    <div className={styles.shell}>
      <a href="#main-content" className="skip-link">
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
              <main id="main-content" tabIndex={-1} className={styles.main}>
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
                <Outlet />
              </main>
              {isSearch && <SearchAskBar />}
            </ProgramsProvider>
          </SearchProvider>
        </AccountContext.Provider>
      </div>
    </div>
  );
}
