import type { ReactNode } from 'react';
import styles from './CourseDetail.module.css';

export function DetailText({
  kind = 'text',
  children,
  title,
}: {
  kind?: 'text' | 'note' | 'heading' | 'warning';
  children: ReactNode;
  title?: string;
}) {
  const Tag = kind === 'heading' ? 'h3' : 'p';
  return (
    <Tag data-kind={kind} className={styles[kind]} title={title}>
      {children}
    </Tag>
  );
}
export function DetailLine({ label, value }: { label: string; value: string }) {
  return (
    <div data-kind="line" className={styles.line}>
      <strong data-label>{label}：</strong>
      <span data-value>{value.replaceAll('\r', '')}</span>
    </div>
  );
}
export function DetailDisclosure({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <details className={styles.disclosure}>
      <summary data-kind="disclosure">{label}</summary>
      <div className={styles.detailsBody}>{children}</div>
    </details>
  );
}
export function DetailLink({
  href,
  children,
  overview = false,
}: {
  href: string;
  children: string;
  overview?: boolean;
}) {
  const before = overview ? '课程描述来自 ' : '';
  const after = overview ? ' 的存档副本，不是实时核对。' : ' · 非实时核验';
  return (
    <p
      data-kind={overview ? 'note_link' : 'link'}
      className={overview ? styles.note : undefined}
    >
      {overview && <span data-before>{before}</span>}
      <a href={href} target="_blank" rel="noopener noreferrer">
        {children}
      </a>
      <span data-after>{after}</span>
    </p>
  );
}
