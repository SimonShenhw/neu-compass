import { useQueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { refreshReads, useShowingOld } from '../api/queries';
import { AccountContext } from './account';
import { AskBar } from './AskBar';
import { usePrototype } from './PrototypeContext';
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

export function AppShell() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const state = usePrototype();
  const comparison = useCompareList();
  const { session, login, logout, account } = useSession(state.announce);
  const showingOld = useShowingOld();
  const box = { session, onLogin: login, onLogout: logout };
  const { title, isSearch, navigationPath } = pagePresentation(pathname);
  useEffect(() => {
    document.title = `${title} · NEU-Compass`;
    document.getElementById('main-content')?.focus({ preventScroll: true });
    window.scrollTo({ top: 0, left: 0, behavior: 'instant' });
  }, [pathname, title]);
  const refresh = () => void refreshReads(queryClient);
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
          onRefresh={refresh}
          account={box}
        />
        <main id="main-content" tabIndex={-1} className={styles.main}>
          <div role="status" aria-label="内容更新" className={styles.fallback}>
            {showingOld && <p>{FALLBACK_NOTICE}</p>}
          </div>
          <AccountContext.Provider value={account}>
            <Outlet />
          </AccountContext.Provider>
        </main>
        <p role="status" className={styles.notice}>
          {state.notice}
        </p>
        {isSearch && (
          <AskBar
            onSend={(question) => {
              state.submit(question);
              if (pathname !== '/') void navigate('/');
            }}
          />
        )}
      </div>
    </div>
  );
}
