import { Compass, Lock } from 'lucide-react';
import type { ComponentProps } from 'react';
import { Link } from 'react-router-dom';
import { MobileNav } from './MobileNav';
import type { Sidebar } from './Sidebar';
import styles from './TopBar.module.css';

export function TopBar({
  title,
  count,
  onRefresh,
  showGuest = true,
  account = {},
}: {
  title: string;
  count: number;
  onRefresh: () => void;
  showGuest?: boolean;
  // The account box for the mobile menu, the same as the desktop sidebar's (R2b).
  account?: Pick<
    ComponentProps<typeof Sidebar>,
    'session' | 'onLogin' | 'onLogout'
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
      <h1 className={title === '数据与隐私' ? styles.privacyTitle : undefined}>
        {title === '数据与隐私' && <Lock aria-hidden="true" />}
        {title}
      </h1>
      <div className={styles.status}>
        <span className={styles.catalog}>
          {title === '课程对比'
            ? `已选 ${count} / 4 门 · 按加入的顺序`
            : '6,469 门课 · 目录 2026–2027'}
        </span>
        {showGuest && <span className={styles.tag}>游客</span>}
      </div>
    </header>
  );
}
