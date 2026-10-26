import { useEffect } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { Sidebar } from '../../layout/Sidebar';
import { TopBar } from '../../layout/TopBar';
import { useNotice } from '../../layout/NoticeContext';
import { pagePresentation } from '../../layout/routePresentation';
import { useCompareList } from '../../models/compareList';
import styles from '../../layout/AppShell.module.css';

// Only synthetic demo routes use this shell. It never mounts useSession or API queries.
export default function OfflineDemoShell() {
  const { pathname } = useLocation();
  const { notice, announce } = useNotice();
  const { title } = pagePresentation(pathname);
  const count = useCompareList().length;
  const account = {
    session: { kind: 'guest' as const, login: 'unavailable' as const },
  };
  const refresh = () => announce('固定合成演示；请使用页面内的重新加载。');
  useEffect(() => {
    document.title = `${title} · NEU-Compass`;
    document.getElementById('main-content')?.focus({ preventScroll: true });
    window.scrollTo({ top: 0, left: 0, behavior: 'instant' });
  }, [pathname, title]);
  return (
    <div className={styles.shell}>
      <a href="#main-content" className="skip-link">
        跳到主要内容
      </a>
      <aside className={styles.desktopSidebar}>
        <Sidebar compareCount={count} onRefresh={refresh} {...account} />
      </aside>
      <div className={styles.mainColumn}>
        <TopBar
          title={title}
          showGuest
          count={count}
          courses={null}
          onRefresh={refresh}
          account={account}
        />
        <main id="main-content" tabIndex={-1} className={styles.main}>
          <Outlet />
        </main>
        <p role="status" className={styles.notice}>
          {notice}
        </p>
      </div>
    </div>
  );
}
