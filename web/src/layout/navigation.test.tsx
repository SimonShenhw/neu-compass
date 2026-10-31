import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
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
it('the footer says what Streamlit’s does, and no filters wait to be built (R6, the user’s choices of 10-29)', () => {
  render(
    <MemoryRouter>
      <Sidebar />
    </MemoryRouter>,
  );
  expect(
    screen.getByText(
      '非官方学生工具 · 课程数据可能滞后，选课请以官方目录为准 · 非商业 / F1 合规',
    ),
  ).toBeInTheDocument();
  expect(screen.queryByText('高级筛选')).not.toBeInTheDocument();
  expect(screen.queryByText(/后续接入|R1 只保留/)).not.toBeInTheDocument();
});
it('a guest can press login only when the API says login works', async () => {
  const user = userEvent.setup();
  const onLogin = vi.fn();
  const { rerender } = render(
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
  expect(screen.getByText('暂时不能登录。')).toBeInTheDocument();
  rerender(
    <MemoryRouter>
      <Sidebar session={{ kind: 'guest', login: 'ready' }} onLogin={onLogin} />
    </MemoryRouter>,
  );
  await user.click(screen.getByRole('button', { name: '用 NEU 邮箱登录' }));
  expect(onLogin).toHaveBeenCalledTimes(1);
  expect(screen.queryByText('暂时不能登录。')).not.toBeInTheDocument();
  for (const [login, label] of [
    ['busy', '正在前往 Google…'],
    ['checking', '用 NEU 邮箱登录'],
  ] as const) {
    rerender(
      <MemoryRouter>
        <Sidebar session={{ kind: 'guest', login, unsure: true }} />
      </MemoryRouter>,
    );
    expect(screen.getByRole('button', { name: label })).toBeDisabled();
    expect(screen.queryByText('暂时不能登录。')).not.toBeInTheDocument();
    expect(screen.getByText('暂时无法确认登录状态。')).toBeInTheDocument();
  }
});
it('a member sees their name and contributions as plain text and can log out', async () => {
  const user = userEvent.setup();
  const onLogout = vi.fn();
  const { rerender } = render(
    <MemoryRouter>
      <Sidebar
        session={{
          kind: 'signed-in',
          displayName: '<b>演示用户</b>',
          contributionCount: 2,
        }}
        onLogout={onLogout}
      />
    </MemoryRouter>,
  );
  expect(screen.getByText('<b>演示用户</b>')).toBeInTheDocument();
  expect(screen.getByText('贡献数：2')).toBeInTheDocument();
  expect(screen.queryByText('用 NEU 邮箱登录')).not.toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: '退出登录' }));
  expect(onLogout).toHaveBeenCalledTimes(1);
  rerender(
    <MemoryRouter>
      <Sidebar
        session={{
          kind: 'signed-in',
          displayName: '演示用户',
          contributionCount: 0,
          busy: true,
        }}
      />
    </MemoryRouter>,
  );
  expect(screen.getByRole('button', { name: '正在退出…' })).toBeDisabled();
});
it('while the login is being checked there is no button at all', () => {
  render(
    <MemoryRouter>
      <Sidebar session={{ kind: 'checking' }} />
    </MemoryRouter>,
  );
  expect(screen.getByText('正在确认登录状态…')).toBeInTheDocument();
  expect(
    screen.queryByRole('button', { name: /登录/ }),
  ).not.toBeInTheDocument();
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
