import { useEffect } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { AskBar } from './AskBar';
import { usePrototype } from './PrototypeContext';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';
import { pagePresentation } from './routePresentation';
import { useCompareList } from '../models/compareList';
import styles from './AppShell.module.css';

export function AppShell() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const state = usePrototype();
  const comparison = useCompareList();
  const { title, isSearch, navigationPath } = pagePresentation(pathname);
  useEffect(() => {
    document.title = `${title} · NEU-Compass`;
    document.getElementById('main-content')?.focus({ preventScroll: true });
    window.scrollTo({ top: 0, left: 0, behavior: 'instant' });
  }, [pathname, title]);
  const refresh = () => state.announce('R1 使用固定假数据；未发送刷新请求。');
  return (
    <div className={styles.shell}>
      <a href="#main-content" className="skip-link">
        跳到主要内容
      </a>
      <aside className={styles.desktopSidebar}>
        <Sidebar compareCount={comparison.length} onRefresh={refresh} />
      </aside>
      <div className={styles.mainColumn}>
        <TopBar
          showGuest={
            navigationPath !== '/coop' && navigationPath !== '/privacy'
          }
          title={title}
          count={comparison.length}
          onRefresh={refresh}
        />
        <main id="main-content" tabIndex={-1} className={styles.main}>
          <Outlet />
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
