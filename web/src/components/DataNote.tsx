import { Info } from 'lucide-react';
import type { ReactNode } from 'react';
import styles from './DataNote.module.css';

export function DataNote({
  children,
  title = '数据说明',
}: {
  children: ReactNode;
  title?: string;
}) {
  return (
    <details className={styles.note}>
      <summary>
        <Info aria-hidden="true" />
        {title}
      </summary>
      <div className={styles.content}>{children}</div>
    </details>
  );
}
