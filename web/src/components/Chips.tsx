import styles from './Chips.module.css';

export function Chips({ items }: { items: readonly string[] }) {
  return (
    <div className={styles.chips}>
      {items.slice(0, 8).map((item) => (
        <span key={item}>{item}</span>
      ))}
      {items.length > 8 && (
        <span
          className={styles.more}
          aria-label={`另外 ${items.length - 8} 个主题`}
        >
          +{items.length - 8}
        </span>
      )}
    </div>
  );
}
