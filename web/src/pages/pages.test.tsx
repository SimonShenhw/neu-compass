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

it('comparison view does not invent a program selection before R4', async () => {
  const user = userEvent.setup();
  page('/compare');
  expect(
    screen.queryByRole('combobox', { name: /按方案看/ }),
  ).not.toBeInTheDocument();
  await user.click(screen.getByRole('link', { name: '查看 CS 6140' }));
  expect(screen.getByRole('combobox', { name: /项目/ })).toHaveTextContent(
    '不指定',
  );
  expect(screen.getByRole('combobox', { name: /^方案/ })).toBeDisabled();
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
    '/compare/',
    '/COURSE/CS-6140',
    '/course/CS-6140/extra',
  ])('has no DOM axe violations at %s', async (path) => {
    const { container } = page(path);
    const result = await axe(container, {
      rules: { 'color-contrast': { enabled: false } },
    });
    expect(result.violations).toEqual([]);
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
  });
});

it.each([
  ['/compare/', '课程对比'],
  ['/COMPARE', '课程对比'],
  ['/programs/', '培养方案'],
  ['/PROGRAMS', '培养方案'],
  ['/coop/', 'Co-op 经验'],
  ['/COOP', 'Co-op 经验'],
  ['/privacy/', '数据与隐私'],
  ['/PRIVACY', '数据与隐私'],
  ['/course/CS-6140/', '课程搜索'],
  ['/COURSE/CS-6140', '课程搜索'],
])('route chrome agrees with the rendered page at %s', (path, title) => {
  page(path);
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(title);
  expect(document.title).toBe(`${title} · NEU-Compass`);
  const nav = screen.getByRole('navigation', { name: '主导航' });
  expect(
    within(nav).getByRole('link', { name: new RegExp(title) }),
  ).toHaveAttribute('aria-current', 'page');
  expect(nav.querySelectorAll('[aria-current="page"]')).toHaveLength(1);
  expect(screen.queryByText('404 · 找不到这个页面')).not.toBeInTheDocument();
  expect(screen.queryByRole('form', { name: '提问' }) !== null).toBe(
    title === '课程搜索',
  );
});
it.each([
  '/course/',
  '/course/CS-6140/extra',
  '/COURSE/CS-6140/extra',
  '/compare/details',
  '/privacy-policy',
])(
  'invalid path %s stays a genuine 404 without search controls or current navigation',
  (path) => {
    page(path);
    expect(screen.getByText('404 · 找不到这个页面')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      '找不到页面',
    );
    expect(document.title).toBe('找不到页面 · NEU-Compass');
    expect(
      screen.queryByRole('form', { name: '提问' }),
    ).not.toBeInTheDocument();
    expect(
      screen
        .getByRole('navigation', { name: '主导航' })
        .querySelector('[aria-current]'),
    ).toBeNull();
  },
);
it('a matched but unknown course remains a search-page empty state rather than a route 404', () => {
  page('/COURSE/UNKNOWN/');
  expect(screen.getByText('找不到这门演示课程：UNKNOWN')).toBeInTheDocument();
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
    '课程搜索',
  );
  expect(screen.getByRole('form', { name: '提问' })).toBeInTheDocument();
  expect(screen.queryByText('404 · 找不到这个页面')).not.toBeInTheDocument();
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
it('all seven comparison rows remain visible and removal keeps other columns', async () => {
  const user = userEvent.setup();
  page('/compare');
  expect(screen.queryByRole('switch')).not.toBeInTheDocument();
  expect(screen.getAllByRole('rowheader').map((el) => el.textContent)).toEqual([
    '官方目录描述',
    '学生评价里的估计',
    '先修／共修',
    '主题',
    '考核构成',
    '在培养方案里的位置',
    '缺的数据',
  ]);
  await user.click(screen.getByRole('button', { name: '移出 CS 6140' }));
  expect(
    screen.queryByRole('link', { name: '查看 CS 6140' }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole('link', { name: '查看 CS 5800' }),
  ).toBeInTheDocument();
  expect(
    within(screen.getByRole('region', { name: '课程对比内容' })).getByText(
      '已选择 3/4 门；按加入顺序展示，不排名、不判断选课或毕业资格。',
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
it.each([
  ['CS 5800', 'CS 6140'],
  ['CS 6140', 'DS 5220'],
  ['CS 5100', 'DS 5220'],
])(
  'removing %s moves keyboard focus to the neighboring %s control',
  async (code, neighbor) => {
    const user = userEvent.setup();
    page('/compare');
    screen.getByRole('button', { name: `移出 ${code}` }).focus();
    await user.keyboard('{Enter}');
    expect(
      screen.queryByRole('button', { name: `移出 ${code}` }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: `移出 ${neighbor}` }),
    ).toHaveFocus();
  },
);
it('removing the last comparison course focuses the empty-state action', async () => {
  const user = userEvent.setup();
  page('/compare');
  for (const code of ['CS 5800', 'CS 6140', 'DS 5220', 'CS 5100']) {
    screen.getByRole('button', { name: `移出 ${code}` }).focus();
    await user.keyboard('{Enter}');
  }
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
  expect(screen.getByRole('link', { name: '回到课程搜索' })).toHaveFocus();
  await user.keyboard('{Enter}');
  expect(screen.getByRole('heading', { name: '课程搜索' })).toBeInTheDocument();
});
it('clearing comparison focuses its remaining keyboard action', async () => {
  const user = userEvent.setup();
  page('/compare');
  screen.getByRole('button', { name: '清空对比' }).focus();
  await user.keyboard('{Enter}');
  expect(screen.getByRole('link', { name: '回到课程搜索' })).toHaveFocus();
});
it('comparison sidebar count follows the external store through removal and clear', async () => {
  const user = userEvent.setup();
  page('/compare');
  const nav = screen.getByRole('navigation', { name: '主导航' });
  expect(within(nav).getByRole('link', { name: /课程对比/ })).toHaveTextContent(
    '4',
  );
  await user.click(screen.getByRole('button', { name: '移出 CS 6140' }));
  expect(within(nav).getByRole('link', { name: /课程对比/ })).toHaveTextContent(
    '3',
  );
  await user.click(screen.getByRole('button', { name: '清空对比' }));
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
  expect(
    within(nav).getByRole('link', { name: /课程对比/ }),
  ).not.toHaveTextContent(/[1-4]/);
});
it.each([
  'CS 5800 讲什么？',
  '适合入门的机器学习课',
  'CS 6140 的先修是什么？',
  'MSCS 第一学期一般选什么？',
])(
  'choosing the empty-page example %s focuses the new answer',
  async (question) => {
    const user = userEvent.setup();
    page('/?demo=empty');
    screen.getByRole('button', { name: question }).focus();
    await user.keyboard('{Enter}');
    expect(screen.getByLabelText('演示问题')).toHaveTextContent(question);
    expect(screen.getByRole('article', { name: '示例回答' })).toHaveFocus();
  },
);
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
      '已选择 3/4 门；按加入顺序展示，不排名、不判断选课或毕业资格。',
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
