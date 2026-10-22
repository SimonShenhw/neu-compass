import type { ComponentPropsWithRef } from 'react';
import styles from './Button.module.css';

export type ButtonProps = ComponentPropsWithRef<'button'> & {
  variant?: 'primary' | 'outline' | 'ghost';
  size?: 'sm' | 'default';
};

export function Button({
  variant = 'outline',
  size = 'default',
  className = '',
  type = 'button',
  ...props
}: ButtonProps) {
  return (
    <button
      {...props}
      type={type}
      className={`${styles.button} ${styles[variant]} ${styles[size]} ${className}`}
    />
  );
}
