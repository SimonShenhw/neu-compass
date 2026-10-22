import type { ReactNode } from 'react';
import styles from './EmptyState.module.css';

export function EmptyState({
  children,
  action,
}: {
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className={styles.empty}>
      <p>{children}</p>
      {action && <div>{action}</div>}
    </div>
  );
}
