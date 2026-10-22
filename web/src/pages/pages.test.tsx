import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { axe } from 'vitest-axe';
import { App } from '../App';

function page(path = '/') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

it('route focus does not scroll the heading out of view', () => {
  const focus = vi.spyOn(HTMLElement.prototype, 'focus');
  page('/course/CS-6140');
  expect(focus).toHaveBeenCalledWith({ preventScroll: true });
});

it('choosing a comparison plan keeps its fixture project consistent on return', async () => {
  const user = userEvent.setup();
  page('/compare');
  screen.getByRole('combobox', { name: /按方案看/ }).focus();
  await user.keyboard('{ArrowDown}{End}{Enter}');
  await user.click(screen.getByRole('link', { name: '查看 CS 6140' }));
  expect(screen.getByRole('combobox', { name: /项目/ })).toHaveTextContent(
    'MSCS',
  );
  expect(screen.getByRole('combobox', { name: /^方案/ })).toHaveTextContent(
    'Boston',
  );
  expect(screen.getByRole('combobox', { name: /^方案/ })).toBeEnabled();
});

describe('page accessibility', () => {
  it.each([
    '/',
    '/?demo=empty',
    '/course/CS-6140',
    '/compare',
    '/programs',
    '/coop',
    '/privacy',
    '/not-found',
    '/course/UNKNOWN',
  ])('has no DOM axe violations at %s', async (path) => {
    const { container } = page(path);
    const result = await axe(container, {
      rules: { 'color-contrast': { enabled: false } },
    });
    expect(result.violations).toEqual([]);
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
  });
});

it('search shows four courses in answer order, and opens an inline detail', async () => {
  const user = userEvent.setup();
  page();
  const courseList = screen.getByRole('region', { name: '回答用到的课' });
  expect(
    within(courseList)
      .getAllByRole('link')
      .map((link) => link.textContent),
  ).toEqual(['查看', '查看', '查看', '查看']);
  expect(
    within(courseList)
      .getAllByRole('link')
      .map((link) => link.getAttribute('href')),
  ).toEqual([
    '/course/CS-6140',
    '/course/DS-5220',
    '/course/CS-5100',
    '/course/CS-5800',
  ]);
  await user.click(screen.getByRole('link', { name: '查看 CS 6140' }));
  expect(
    screen.getByRole('region', { name: 'CS 6140 课程详情' }),
  ).toBeInTheDocument();
  expect(screen.getByRole('article', { name: '示例回答' })).toBeInTheDocument();
});
it('empty demo has four working example questions', async () => {
  const user = userEvent.setup();
  page('/?demo=empty');
  expect(
    screen.getByRole('heading', { name: '问一门课，或者一个选课问题' }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole('article', { name: '示例回答' }),
  ).not.toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'CS 5800 讲什么？' }));
  expect(screen.getByLabelText('演示问题')).toHaveTextContent(
    'CS 5800 讲什么？',
  );
  expect(screen.getByRole('article', { name: '示例回答' })).toBeInTheDocument();
});
it('plus only records a demo action without changing the comparison', async () => {
  const user = userEvent.setup();
  const log = vi.spyOn(console, 'info').mockImplementation(() => {});
  page();
  await user.click(screen.getByRole('button', { name: '加入对比 CS 6140' }));
  expect(log).toHaveBeenCalledExactlyOnceWith('prototype.compare', 'CS 6140');
  expect(screen.getByRole('status')).toHaveTextContent(
    'R1 不向对比列表添加数据',
  );
});
it('detail leaf navigation opens the exact prerequisite and resets expansion', async () => {
  const user = userEvent.setup();
  page('/course/CS-6140');
  await user.click(screen.getByRole('button', { name: '展开全文' }));
  expect(screen.getByRole('button', { name: '收起全文' })).toHaveAttribute(
    'aria-expanded',
    'true',
  );
  await user.click(
    screen.getByRole('button', { name: /CS 7800 Advanced Algorithms/ }),
  );
  expect(
    screen.getByRole('region', { name: 'CS 7800 课程详情' }),
  ).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '展开全文' })).toHaveAttribute(
    'aria-expanded',
    'false',
  );
});
it('compare switch restores shared rows and removal keeps other columns', async () => {
  const user = userEvent.setup();
  page('/compare');
  expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'true');
  expect(
    screen.queryByRole('rowheader', { name: '学分' }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole('rowheader', { name: '目录年份' }),
  ).not.toBeInTheDocument();
  await user.click(screen.getByRole('switch'));
  expect(screen.getByRole('rowheader', { name: '学分' })).toBeInTheDocument();
  expect(
    screen.getByRole('rowheader', { name: '目录年份' }),
  ).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: '移出 CS 6140' }));
  expect(
    screen.queryByRole('link', { name: '查看 CS 6140' }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole('link', { name: '查看 CS 5800' }),
  ).toBeInTheDocument();
  expect(
    within(screen.getByRole('region', { name: '课程对比内容' })).getByText(
      '已选 3 / 4 门 · 按加入的顺序',
    ),
  ).toBeInTheDocument();
});
it('clearing comparison produces a usable empty state', async () => {
  page('/compare');
  await userEvent.click(screen.getByRole('button', { name: '清空对比' }));
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
  expect(screen.getByRole('link', { name: '回到课程搜索' })).toHaveAttribute(
    'href',
    '/',
  );
});
it('compare removal survives route navigation within the prototype', async () => {
  const user = userEvent.setup();
  page('/compare');
  await user.click(screen.getByRole('button', { name: '移出 CS 6140' }));
  await user.click(screen.getByRole('link', { name: '查看 CS 5800' }));
  await user.click(screen.getByRole('link', { name: /课程对比/ }));
  expect(
    screen.queryByRole('button', { name: '移出 CS 6140' }),
  ).not.toBeInTheDocument();
  expect(
    within(screen.getByRole('region', { name: '课程对比内容' })).getByText(
      '已选 3 / 4 门 · 按加入的顺序',
    ),
  ).toBeInTheDocument();
});
it('project and plan choices survive route navigation and a project change clears the plan', async () => {
  const user = userEvent.setup();
  page();
  const project = screen.getByRole('combobox', { name: /项目/ });
  project.focus();
  await user.keyboard('{ArrowDown}{End}{Enter}');
  const plan = screen.getByRole('combobox', { name: /^方案/ });
  plan.focus();
  await user.keyboard('{ArrowDown}{End}{Enter}');
  expect(plan).toHaveTextContent('Boston');
  await user.click(screen.getByRole('link', { name: '查看 CS 6140' }));
  expect(screen.getByRole('combobox', { name: /项目/ })).toHaveTextContent(
    'MSCS',
  );
  expect(screen.getByRole('combobox', { name: /^方案/ })).toHaveTextContent(
    'Boston',
  );
  screen.getByRole('combobox', { name: /项目/ }).focus();
  await user.keyboard('{ArrowDown}{Home}{Enter}');
  expect(screen.getByRole('combobox', { name: /^方案/ })).toHaveTextContent(
    '不指定',
  );
  expect(screen.getByRole('combobox', { name: /^方案/ })).toBeDisabled();
});
it('unrecognized paths give a working home link', async () => {
  page('/missing');
  await userEvent.click(screen.getByRole('link', { name: '返回首页' }));
  expect(screen.getByRole('heading', { name: '课程搜索' })).toBeInTheDocument();
});
