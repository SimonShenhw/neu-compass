import styles from './Toggle.module.css';

export function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={styles.toggle}
    >
      <span className={styles.track} aria-hidden="true">
        <span className={styles.knob} />
      </span>
      <span>{label}</span>
    </button>
  );
}
