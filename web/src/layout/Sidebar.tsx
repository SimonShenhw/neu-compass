import {
  BookOpen,
  BriefcaseBusiness,
  Columns3,
  Compass,
  LockKeyhole,
  RefreshCw,
  Search,
} from 'lucide-react';
import { Link, useLocation } from 'react-router-dom';
import { Button } from '../components/Button';
import { pagePresentation } from './routePresentation';
import styles from './Sidebar.module.css';

export type SessionView =
  { kind: 'guest' } | { kind: 'signed-in'; displayName: string };
export function Sidebar({
  session = { kind: 'guest' },
  compareCount = 0,
  onNavigate,
  onRefresh,
}: {
  session?: SessionView;
  compareCount?: number;
  onNavigate?: () => void;
  onRefresh?: () => void;
}) {
  const { pathname } = useLocation();
  const { navigationPath } = pagePresentation(pathname);
  const links = [
    { path: '/', label: '课程搜索', icon: Search },
    { path: '/programs', label: '培养方案', icon: BookOpen },
    { path: '/coop', label: 'Co-op 经验', icon: BriefcaseBusiness },
    { path: '/compare', label: '课程对比', icon: Columns3 },
    { path: '/privacy', label: '数据与隐私', icon: LockKeyhole },
  ];
  return (
    <div className={styles.sidebar}>
      <Link to="/" className={styles.brand} onClick={onNavigate}>
        <Compass aria-hidden="true" />
        <span>
          <strong>NEU-Compass</strong>
          <small>选课助手</small>
        </span>
      </Link>
      <div className={styles.account}>
        {session.kind === 'guest' ? (
          <>
            <Button disabled title="R1 不接登录；R2 接入">
              用 NEU 邮箱登录
            </Button>
            <small>只限 husky.neu.edu、northeastern.edu</small>
          </>
        ) : (
          <>
            <strong>{session.displayName}</strong>
            <small>已登录（组件演示）</small>
            <Button variant="ghost" disabled>
              退出登录
            </Button>
          </>
        )}
      </div>
      <nav aria-label="主导航" className={styles.navigation}>
        {links.map(({ path, label, icon: Icon }) => {
          const active = path === navigationPath;
          return (
            <Link
              to={path}
              key={path}
              aria-current={active ? 'page' : undefined}
              className={active ? styles.active : ''}
              onClick={onNavigate}
            >
              <Icon aria-hidden="true" />
              <span>{label}</span>
              {path === '/compare' && (
                <span className={styles.count}>{compareCount}</span>
              )}
            </Link>
          );
        })}
      </nav>
      <details className={styles.filters}>
        <summary>高级筛选</summary>
        <p>筛选交互将在后续接入；R1 只保留入口。</p>
      </details>
      <div className={styles.footer}>
        <Button size="sm" variant="ghost" onClick={onRefresh}>
          <RefreshCw aria-hidden="true" />
          刷新课程数据
        </Button>
        <small>非官方学生工具 · 选课以官方目录为准</small>
        <small>假数据原型 · 不接接口、不存储</small>
      </div>
    </div>
  );
}
