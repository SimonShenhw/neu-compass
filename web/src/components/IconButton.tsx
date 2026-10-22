import type { ButtonProps } from './Button';
import { Button } from './Button';
import styles from './IconButton.module.css';

export type IconButtonProps = Omit<ButtonProps, 'aria-label'> & {
  'aria-label': string;
};

export function IconButton({ className = '', ...props }: IconButtonProps) {
  return <Button {...props} className={`${styles.iconButton} ${className}`} />;
}
