import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { expect, it } from 'vitest';
import { Sidebar } from './Sidebar';
import { MobileNav } from './MobileNav';

it.each([
  ['/', '课程搜索'],
  ['/course/CS-6140', '课程搜索'],
  ['/compare', '课程对比'],
  ['/programs', '培养方案'],
  ['/coop', 'Co-op 经验'],
  ['/privacy', '数据与隐私'],
])('marks only the current destination for %s', (path, label) => {
  render(
    <MemoryRouter initialEntries={[path ?? '/']}>
      <Sidebar compareCount={4} />
    </MemoryRouter>,
  );
  const nav = screen.getByRole('navigation', { name: '主导航' });
  expect(
    within(nav).getByRole('link', { name: new RegExp(label ?? '') }),
  ).toHaveAttribute('aria-current', 'page');
  expect(nav.querySelectorAll('[aria-current="page"]')).toHaveLength(1);
});
it('has a guest view with no working login integration', () => {
  render(
    <MemoryRouter>
      <Sidebar />
    </MemoryRouter>,
  );
  expect(
    screen.getByRole('button', { name: '用 NEU 邮箱登录' }),
  ).toBeDisabled();
  expect(
    screen.getByText('只限 husky.neu.edu、northeastern.edu'),
  ).toBeInTheDocument();
});
it('supports the signed-in component view using synthetic data only', () => {
  render(
    <MemoryRouter>
      <Sidebar session={{ kind: 'signed-in', displayName: '演示用户' }} />
    </MemoryRouter>,
  );
  expect(screen.getByText('演示用户')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '退出登录' })).toBeDisabled();
  expect(screen.queryByText('用 NEU 邮箱登录')).not.toBeInTheDocument();
});
it('mobile trigger reports expansion, Escape closes and restores focus', async () => {
  const user = userEvent.setup();
  render(
    <MemoryRouter>
      <MobileNav />
    </MemoryRouter>,
  );
  const trigger = screen.getByRole('button', { name: '打开导航菜单' });
  expect(trigger).toHaveAttribute('aria-expanded', 'false');
  await user.click(trigger);
  expect(trigger).toHaveAttribute('aria-expanded', 'true');
  expect(screen.getByRole('dialog', { name: '导航菜单' })).toBeInTheDocument();
  await user.keyboard('{Escape}');
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(trigger).toHaveAttribute('aria-expanded', 'false');
  expect(trigger).toHaveFocus();
});
it('choosing a mobile destination closes the drawer', async () => {
  const user = userEvent.setup();
  render(
    <MemoryRouter>
      <MobileNav />
    </MemoryRouter>,
  );
  await user.click(screen.getByRole('button', { name: '打开导航菜单' }));
  const dialog = screen.getByRole('dialog');
  await user.click(within(dialog).getByRole('link', { name: /课程对比/ }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: '打开导航菜单' })).toHaveAttribute(
    'aria-expanded',
    'false',
  );
});
