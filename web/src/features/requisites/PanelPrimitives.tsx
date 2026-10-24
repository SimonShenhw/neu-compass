import { createContext, useContext } from 'react';
import type { ReactNode } from 'react';
import { Select } from '../../components/Select';
import styles from './Requisites.module.css';

export const PanelContext = createContext({ part: 'requisites', depth: 0 });
export function Line({
  kind = 'text',
  children,
}: {
  kind?: 'heading' | 'note' | 'text' | 'warning';
  children: ReactNode;
}) {
  const context = useContext(PanelContext);
  const Tag = kind === 'heading' ? 'h3' : 'p';
  return (
    <Tag
      data-kind={kind}
      data-part={context.part}
      data-depth={context.depth}
      className={styles[kind]}
    >
      {children}
    </Tag>
  );
}
export function Disclosure({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  const context = useContext(PanelContext);
  return (
    <details className={styles.disclosure}>
      <summary
        data-kind="disclosure"
        data-part={context.part}
        data-depth={context.depth}
      >
        {label}
      </summary>
      <PanelContext value={{ ...context, depth: context.depth + 1 }}>
        <div className={styles.detailsBody}>{children}</div>
      </PanelContext>
    </details>
  );
}
export function PanelSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
}) {
  const context = useContext(PanelContext);
  return (
    <div
      className={styles.select}
      data-kind="select"
      data-part={context.part}
      data-depth={context.depth}
    >
      <Select
        label={label}
        value={value}
        onChange={onChange}
        options={options}
      />
    </div>
  );
}
export function SourceLink({
  href,
  children,
}: {
  href: string;
  children: string;
}) {
  const context = useContext(PanelContext);
  return (
    <a
      data-kind="link"
      data-part={context.part}
      data-depth={context.depth}
      href={href}
      target="_blank"
      rel="noopener noreferrer"
    >
      {children}
    </a>
  );
}
