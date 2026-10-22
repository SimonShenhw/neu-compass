import styles from './CourseCode.module.css';

export function CourseCode({
  children,
  size = 'default',
}: {
  children: string;
  size?: 'default' | 'lg';
}) {
  return (
    <span className={`${styles.code} ${size === 'lg' ? styles.lg : ''}`}>
      {children}
    </span>
  );
}
