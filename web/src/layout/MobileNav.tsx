import * as Dialog from '@radix-ui/react-dialog';
import { Menu, X } from 'lucide-react';
import { useState } from 'react';
import { IconButton } from '../components/IconButton';
import { Sidebar } from './Sidebar';
import type { ComponentProps } from 'react';
import styles from './MobileNav.module.css';

export function MobileNav(props: ComponentProps<typeof Sidebar>) {
  const [open, setOpen] = useState(false);
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <IconButton
          aria-label="打开导航菜单"
          variant="ghost"
          aria-expanded={open}
        >
          <Menu aria-hidden="true" />
        </IconButton>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.overlay} />
        <Dialog.Content className={styles.drawer}>
          <Dialog.Title className="visually-hidden">导航菜单</Dialog.Title>
          <Dialog.Description className="visually-hidden">
            选择页面；按 Escape 关闭菜单并返回打开菜单的按钮。
          </Dialog.Description>
          <div className={styles.close}>
            <Dialog.Close asChild>
              <IconButton aria-label="关闭导航菜单" variant="ghost">
                <X aria-hidden="true" />
              </IconButton>
            </Dialog.Close>
          </div>
          <Sidebar {...props} onNavigate={() => setOpen(false)} />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
