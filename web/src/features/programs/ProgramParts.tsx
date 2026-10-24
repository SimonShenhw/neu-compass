import type { ReactNode } from 'react';
import styles from './Programs.module.css';

export function Line({
  kind = 'text',
  children,
}: {
  kind?: 'text' | 'note' | 'info' | 'warning' | 'share_url';
  children: ReactNode;
}) {
  return (
    <p
      data-kind={kind}
      className={`${styles.line} ${styles[kind] ?? ''}`}
      role={kind === 'warning' ? 'alert' : undefined}
    >
      {children}
    </p>
  );
}
export function Disclosure({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <details className={styles.disclosure}>
      <summary data-kind="disclosure">{title}</summary>
      <div>{children}</div>
    </details>
  );
}
export function SourceLink({
  href,
  children,
}: {
  href: string;
  children: ReactNode;
}) {
  return (
    <a data-kind="link" href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  );
}
