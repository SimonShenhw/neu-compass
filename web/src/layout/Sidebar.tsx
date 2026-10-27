import {
  BookOpen,
  BriefcaseBusiness,
  Columns3,
  Compass,
  LockKeyhole,
  RefreshCw,
  Search,
} from 'lucide-react';
import { useLayoutEffect, useRef } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Button } from '../components/Button';
import { pagePresentation } from './routePresentation';
import styles from './Sidebar.module.css';

// What the account box shows (R2b): AppShell works it out from /config, /auth/me and a login or logout in flight.
export type SessionView =
  | { kind: 'checking' }
  | {
      kind: 'guest';
      // ready: /config says login works; unavailable: it says not, or could not be read.
      login: 'ready' | 'busy' | 'checking' | 'unavailable';
      // /auth/me failed for a moment, so this may be a member shown as a guest.
      unsure?: boolean;
    }
  | {
      kind: 'signed-in';
      displayName: string;
      contributionCount: number;
      busy?: boolean;
    };
export function Sidebar({
  session = { kind: 'guest', login: 'unavailable' },
  compareCount = 0,
  onNavigate,
  onRefresh,
  onLogin,
  onLogout,
  note = '',
}: {
  session?: SessionView;
  compareCount?: number;
  onNavigate?: () => void;
  onRefresh?: () => void;
  onLogin?: () => void;
  onLogout?: () => void;
  // What the last login or logout pressed here came to, by its button, in the sidebar and the mobile menu alike (R3e).
  note?: string;
}) {
  const { pathname } = useLocation();
  const { navigationPath } = pagePresentation(pathname);
  const box = useRef<HTMLDivElement>(null);
  const action = useRef<HTMLButtonElement>(null);
  // The button pressed here is disabled while it works, and a logout replaces it, so focus falls to the page or the
  // menu around it. When the work ends, focus goes to the box's button again, unless the student has moved on; in
  // the same commit that shows the result, so the result is never on screen with focus lost.
  const pressed = useRef(false);
  const busy =
    (session.kind === 'guest' && session.login === 'busy') ||
    (session.kind === 'signed-in' && session.busy === true);
  useLayoutEffect(() => {
    if (busy || !pressed.current) return;
    pressed.current = false;
    const active = document.activeElement;
    if (active === null || active.contains(box.current))
      action.current?.focus();
  }, [busy]);
  const press = (handler?: () => void) => () => {
    pressed.current = true;
    handler?.();
  };
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
      <div className={styles.account} ref={box}>
        {session.kind === 'checking' ? (
          <small>正在确认登录状态…</small>
        ) : session.kind === 'guest' ? (
          <>
            <Button
              ref={action}
              disabled={session.login !== 'ready'}
              onClick={press(onLogin)}
            >
              {session.login === 'busy'
                ? '正在前往 Google…'
                : '用 NEU 邮箱登录'}
            </Button>
            <small>只限 husky.neu.edu、northeastern.edu</small>
            {session.login === 'unavailable' && <small>暂时不能登录。</small>}
            {session.unsure && <small>暂时无法确认登录状态。</small>}
          </>
        ) : (
          <>
            <strong>{session.displayName}</strong>
            <small>贡献数：{session.contributionCount}</small>
            <Button
              ref={action}
              variant="ghost"
              disabled={session.busy === true}
              onClick={press(onLogout)}
            >
              {session.busy ? '正在退出…' : '退出登录'}
            </Button>
          </>
        )}
        {/* Always there, so a screen reader hears it change; out of the layout while it is empty. */}
        <p role="status" className={note ? styles.note : 'visually-hidden'}>
          {note}
        </p>
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
          刷新页面内容
        </Button>
        <small>非官方学生工具 · 选课以官方目录为准</small>
      </div>
    </div>
  );
}
