import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { axe } from 'vitest-axe';
import { App } from '../App';
import privacy from '../fixtures/privacy/privacy-90-days-feedback-contact.json';
import { WithApi } from '../test/withApi';

function page(path = '/') {
  return render(
    <WithApi>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </WithApi>,
  );
}
// The live pages ask the API (R5d, R3e): here /coop and /programs have no rows yet, /privacy answers with a fixture and
// /resolve/course knows no course.
beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      const { pathname, searchParams } = new URL(url);
      if (pathname === '/coop' || pathname === '/programs')
        return new Response('[]');
      if (pathname === '/privacy')
        return new Response(JSON.stringify(privacy.body));
      if (pathname === '/resolve/course')
        return new Response(
          JSON.stringify({ ref: searchParams.get('ref'), matches: [] }),
        );
      return new Response(null, { status: 404 });
    }),
  );
});
// Until no live page is loading or looking anything up any more.
const settled = () =>
  waitFor(() =>
    expect(screen.queryByText(/^正在(加载|查找)/)).not.toBeInTheDocument(),
  );

it('route focus does not scroll the heading out of view', () => {
  const focus = vi.spyOn(HTMLElement.prototype, 'focus');
  page('/course/CS-6140');
  expect(focus).toHaveBeenCalledWith({ preventScroll: true });
});

describe('page accessibility', () => {
  it.each([
    '/',
    '/course/CS-6140',
    '/compare',
    '/programs',
    '/coop',
    '/privacy',
    '/compare-demo',
    '/coop-demo',
    '/privacy-demo',
    '/not-found',
    '/course/UNKNOWN',
    '/compare/',
    '/compare-demo/',
    '/COURSE/CS-6140',
    '/course/CS-6140/extra',
  ])('has no DOM axe violations at %s', async (path) => {
    const { container } = page(path);
    await settled();
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
])('route chrome agrees with the rendered page at %s', async (path, title) => {
  page(path);
  await settled();
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
  ['/compare-demo', '课程对比演示'],
  ['/coop-demo', 'Co-op 演示'],
  ['/privacy-demo', '数据与隐私演示'],
])(
  'the demo at %s has its own title and no current navigation item (R5d)',
  (path, title) => {
    page(path);
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(title);
    expect(document.title).toBe(`${title} · NEU-Compass`);
    expect(
      screen
        .getByRole('navigation', { name: '主导航' })
        .querySelector('[aria-current]'),
    ).toBeNull();
    expect(screen.queryByText('404 · 找不到这个页面')).not.toBeInTheDocument();
  },
);
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
it('an address that names no course is a course page saying so, not a route 404', async () => {
  page('/COURSE/UNKNOWN/');
  expect(
    await screen.findByText(
      '链接指向的课程「UNKNOWN」没找到：可能已经停开，或者链接被截断了。',
    ),
  ).toBeInTheDocument();
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
    '课程搜索',
  );
  expect(screen.getByRole('form', { name: '提问' })).toBeInTheDocument();
  expect(screen.queryByText('404 · 找不到这个页面')).not.toBeInTheDocument();
});
it('all seven comparison rows remain visible and removal keeps other columns', async () => {
  const user = userEvent.setup();
  page('/compare-demo');
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
  page('/compare-demo');
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
    page('/compare-demo');
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
  page('/compare-demo');
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
  page('/compare-demo');
  screen.getByRole('button', { name: '清空对比' }).focus();
  await user.keyboard('{Enter}');
  expect(screen.getByRole('link', { name: '回到课程搜索' })).toHaveFocus();
});
it('unrecognized paths give a working home link', async () => {
  page('/missing');
  await userEvent.click(screen.getByRole('link', { name: '返回首页' }));
  expect(screen.getByRole('heading', { name: '课程搜索' })).toBeInTheDocument();
});
