import { Compass, Lock } from 'lucide-react';
import type { ComponentProps } from 'react';
import { Link } from 'react-router-dom';
import { MobileNav } from './MobileNav';
import type { Sidebar } from './Sidebar';
import styles from './TopBar.module.css';

// The privacy page and its demo carry the lock (R5c, R5d).
const PRIVACY = new Set(['数据与隐私', '数据与隐私演示']);

export function TopBar({
  title,
  count,
  courses,
  onRefresh,
  showGuest = true,
  account = {},
}: {
  title: string;
  count: number;
  // How many courses the API has indexed (GET /ready); null when it has not said (R3e).
  courses: number | null;
  onRefresh: () => void;
  showGuest?: boolean;
  // The account box for the mobile menu, the same as the desktop sidebar's (R2b).
  account?: Pick<
    ComponentProps<typeof Sidebar>,
    'session' | 'onLogin' | 'onLogout' | 'note'
  >;
}) {
  return (
    <header
      className={`${styles.topbar} ${title === '课程搜索' ? styles.searchHeader : ''}`}
    >
      <div className={styles.mobile}>
        <MobileNav compareCount={count} onRefresh={onRefresh} {...account} />
        <Link to="/" className={styles.brand}>
          <Compass aria-hidden="true" />
          NEU-Compass
        </Link>
      </div>
      <h1 className={PRIVACY.has(title) ? styles.privacyTitle : undefined}>
        {PRIVACY.has(title) && <Lock aria-hidden="true" />}
        {title}
      </h1>
      <div className={styles.status}>
        <span className={styles.catalog}>
          {title === '课程对比'
            ? `已选 ${count} / 4 门 · 按加入的顺序`
            : courses === null
              ? 'NEU 研究生课程目录'
              : `${courses.toLocaleString('en-US')} 门课`}
        </span>
        {showGuest && <span className={styles.tag}>游客</span>}
      </div>
    </header>
  );
}
