import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { axe } from 'vitest-axe';
import cs5100 from '../fixtures/compare/course-cs-5100.json';
import cs5800 from '../fixtures/compare/course-cs-5800.json';
import cs6140 from '../fixtures/compare/course-cs-6140.json';
import cs7800 from '../fixtures/compare/course-cs-7800.json';
import ds5220 from '../fixtures/compare/course-ds-5220.json';
import { FALLBACK_NOTICE } from '../layout/AppShell';
import { addToCompare, getCompareList } from '../models/compareList';
import {
  apiError,
  asked,
  fakeApi,
  held,
  json,
  livePage,
} from '../test/fakeApi';

const courses = [cs5800, cs6140, ds5220, cs5100, cs7800].map((f) => f.body);
const byPath = new Map(
  courses.map((body) => [`/course/${body.course_id}`, body]),
);
// Every course in the fixtures answers; anything else is not found.
const catalog = ({ path }: { path: string }) => {
  const body = byPath.get(path);
  return body ? json(body) : apiError(404, 'not_found', 'Course not found');
};
function choose(...ids: string[]) {
  act(() => {
    for (const id of ids) addToCompare(id);
  });
}
// The desktop sidebar (a page may have an aside of its own, as Co-op's does).
const sidebar = () =>
  screen.getByRole('navigation', { name: '主导航' }).closest('aside')!;
const fallback = () => screen.getByRole('status', { name: '内容更新' });

it('an empty comparison asks for nothing', () => {
  const api = fakeApi(catalog);
  livePage('/compare');
  expect(
    screen.getByText(
      '在「课程搜索」页打开一门课的详情，点「加入对比」，最多选择 4 门课。',
    ),
  ).toBeInTheDocument();
  expect(api.calls).toHaveLength(0);
  expect(
    screen.getByRole('heading', { level: 1 }).closest('header'),
  ).toHaveTextContent('游客');
});

it('each course in the list is asked for once, by its ID, in the order it was added', async () => {
  const api = fakeApi(catalog);
  choose('c-cs-6140', 'c-cs-5800');
  livePage('/compare');
  expect(
    await screen.findByRole('link', { name: '查看 CS 5800' }),
  ).toBeInTheDocument();
  expect(api.calls.map(asked)).toEqual([
    'GET /course/c-cs-6140',
    'GET /course/c-cs-5800',
  ]);
  expect(
    screen
      .getAllByRole('columnheader')
      .slice(1)
      .map((cell) => cell.textContent),
  ).toEqual([
    expect.stringContaining('CS 6140'),
    expect.stringContaining('CS 5800'),
  ]);
});

it('an ID goes into the path encoded', async () => {
  const api = fakeApi(catalog);
  choose('c/../x y');
  livePage('/compare');
  expect(await screen.findByText(/没有找到这门课/)).toBeInTheDocument();
  expect(api.calls[0]!.path).toBe('/course/c%2F..%2Fx%20y');
});

it('a failed column says why on its own, and 重新加载 asks again for the failed ones only', async () => {
  const user = userEvent.setup();
  let lost = true;
  const api = fakeApi(({ path }) => {
    if (path === '/course/c-gone')
      return apiError(404, 'not_found', 'Course not found');
    if (path === '/course/c-lost') {
      if (lost) throw new TypeError('Failed to fetch');
      return json({ ...cs7800.body, course_id: 'c-lost' });
    }
    return catalog({ path });
  });
  choose('c-cs-5800', 'c-gone', 'c-lost');
  livePage('/compare');
  expect(
    await screen.findByText('课程加载失败（c-gone）：没有找到这门课。'),
  ).toBeInTheDocument();
  expect(
    screen.getByText(
      '课程加载失败（c-lost）：暂时连不上服务，请稍后重新加载。',
    ),
  ).toBeInTheDocument();
  expect(
    screen.getByRole('link', { name: '查看 CS 5800' }),
  ).toBeInTheDocument();
  lost = false;
  await user.click(screen.getByRole('button', { name: '重新加载' }));
  expect(
    await screen.findByRole('link', { name: '查看 CS 7800' }),
  ).toBeInTheDocument();
  expect(api.count('GET', '/course/c-cs-5800')).toBe(1);
  expect(api.count('GET', '/course/c-gone')).toBe(2);
  expect(api.count('GET', '/course/c-lost')).toBe(2);
  expect(
    screen.getByText('课程加载失败（c-gone）：没有找到这门课。'),
  ).toBeInTheDocument();
});

// The button goes as the column it asks for loads (R5d's wiring shows loading), so focus used to fall to the body
// (section 35's known item); now it goes to the table, which stays, without scrolling (R6).
it('重新加载 hands focus to the table, which is still there once the column it asked for has come back', async () => {
  const user = userEvent.setup();
  const later = held();
  let lost = true;
  fakeApi(({ path }) => {
    if (path !== '/course/c-lost') return catalog({ path });
    if (lost) throw new TypeError('Failed to fetch');
    return later.response;
  });
  choose('c-cs-5800', 'c-lost');
  livePage('/compare');
  await screen.findByText(
    '课程加载失败（c-lost）：暂时连不上服务，请稍后重新加载。',
  );
  lost = false;
  const focus = vi.spyOn(HTMLElement.prototype, 'focus');
  await user.click(screen.getByRole('button', { name: '重新加载' }));
  const table = screen.getByRole('region', { name: '课程对比表，可横向滚动' });
  expect(table).toHaveFocus();
  expect(
    screen.queryByRole('button', { name: '重新加载' }),
  ).not.toBeInTheDocument();
  expect(focus.mock.calls[focus.mock.contexts.indexOf(table)]).toEqual([
    { preventScroll: true },
  ]);
  later.answer(json({ ...cs7800.body, course_id: 'c-lost' }));
  expect(
    await screen.findByRole('link', { name: '查看 CS 7800' }),
  ).toBeInTheDocument();
  expect(table).toHaveFocus();
});

// A column still on its way is not asked again (B27, X16). For a course that answered before, TanStack would cancel
// the request and send another (a query with no data yet just keeps the request it has), so this one answers first,
// fails on a later visit, and is still on its way when 重新加载 is pressed again for the course that keeps failing.
it('重新加载 again leaves alone a column still on its way', async () => {
  const user = userEvent.setup();
  const third = held();
  const answers = [
    () => json(cs5800.body),
    () => apiError(404, 'not_found', 'Course not found'),
    () => third.response,
  ];
  const api = fakeApi(({ path }) =>
    path === '/course/c-cs-5800' ? answers.shift()!() : catalog({ path }),
  );
  choose('c-gone', 'c-cs-5800');
  livePage('/compare');
  await screen.findByRole('link', { name: '查看 CS 5800' });
  await user.click(within(sidebar()).getByRole('link', { name: /培养方案/ }));
  await user.click(within(sidebar()).getByRole('link', { name: /课程对比/ }));
  expect(
    await screen.findByText('课程加载失败（c-cs-5800）：没有找到这门课。'),
  ).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: '重新加载' }));
  await waitFor(() => {
    expect(api.count('GET', '/course/c-gone')).toBe(3);
    expect(
      screen.getByText('课程加载失败（c-gone）：没有找到这门课。'),
    ).toBeInTheDocument();
    expect(
      screen.queryByText('课程加载失败（c-cs-5800）：没有找到这门课。'),
    ).not.toBeInTheDocument();
  });
  expect(api.count('GET', '/course/c-cs-5800')).toBe(3);
  await user.click(screen.getByRole('button', { name: '重新加载' }));
  await waitFor(() => expect(api.count('GET', '/course/c-gone')).toBe(4));
  expect(api.count('GET', '/course/c-cs-5800')).toBe(3);
  third.answer(json(cs5800.body));
  expect(
    await screen.findByRole('link', { name: '查看 CS 5800' }),
  ).toBeInTheDocument();
  expect(api.count('GET', '/course/c-cs-5800')).toBe(3);
});

it('a column asked again shows as loading until its answer', async () => {
  const user = userEvent.setup();
  const second = held();
  let tries = 0;
  fakeApi(({ path }) =>
    path === '/course/c-cs-5800'
      ? tries++
        ? second.response
        : apiError(503, 'service_unavailable', 'down')
      : catalog({ path }),
  );
  choose('c-cs-5800');
  livePage('/compare');
  expect(
    await screen.findByText(
      '课程加载失败（c-cs-5800）：服务暂时出错，请稍后重新加载。',
    ),
  ).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: '重新加载' }));
  await waitFor(() =>
    expect(
      screen.queryByText(
        '课程加载失败（c-cs-5800）：服务暂时出错，请稍后重新加载。',
      ),
    ).not.toBeInTheDocument(),
  );
  expect(screen.getAllByText('正在加载').length).toBeGreaterThan(0);
  second.answer(json(cs5800.body));
  expect(
    await screen.findByRole('link', { name: '查看 CS 5800' }),
  ).toBeInTheDocument();
});

it('an answer the page cannot read is a failed column, and 重新加载 asks for it again', async () => {
  const user = userEvent.setup();
  let tries = 0;
  const api = fakeApi(({ path }) =>
    path === '/course/c-odd'
      ? json(
          tries++
            ? { ...cs6140.body, course_id: 'c-odd' }
            : { course_id: 'c-odd' },
        )
      : catalog({ path }),
  );
  choose('c-odd');
  livePage('/compare');
  expect(
    await screen.findByText(/服务返回了无法识别的内容/),
  ).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: '重新加载' }));
  expect(
    await screen.findByRole('link', { name: '查看 CS 6140' }),
  ).toBeInTheDocument();
  expect(api.count('GET', '/course/c-odd')).toBe(2);
});

// The list holds four at most, so the route's own cut at four (M04) cannot be seen from here.
it('a full list of four asks for each course once', async () => {
  const api = fakeApi(catalog);
  choose('c-cs-5800', 'c-cs-6140', 'c-ds-5220', 'c-cs-5100');
  livePage('/compare');
  await screen.findByRole('link', { name: '查看 CS 5100' });
  expect(api.calls).toHaveLength(4);
  expect(getCompareList()).toHaveLength(4);
});

it('every visit asks again; a temporary failure then keeps the last answer and says so', async () => {
  const user = userEvent.setup();
  let tries = 0;
  const api = fakeApi(({ path }) =>
    path === '/course/c-cs-5800'
      ? tries++
        ? apiError(503, 'service_unavailable', 'down')
        : json(cs5800.body)
      : catalog({ path }),
  );
  choose('c-cs-5800');
  livePage('/compare');
  await screen.findByRole('link', { name: '查看 CS 5800' });
  await user.click(within(sidebar()).getByRole('link', { name: /培养方案/ }));
  await user.click(within(sidebar()).getByRole('link', { name: /课程对比/ }));
  await waitFor(() => expect(fallback()).toHaveTextContent(FALLBACK_NOTICE));
  expect(api.count('GET', '/course/c-cs-5800')).toBe(2);
  expect(
    screen.getByRole('link', { name: '查看 CS 5800' }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole('button', { name: '重新加载' }),
  ).not.toBeInTheDocument();
});

it('a definite answer on a later visit shows nothing old', async () => {
  const user = userEvent.setup();
  let tries = 0;
  fakeApi(({ path }) =>
    path === '/course/c-cs-5800'
      ? tries++
        ? apiError(404, 'not_found', 'Course not found')
        : json(cs5800.body)
      : catalog({ path }),
  );
  choose('c-cs-5800');
  livePage('/compare');
  await screen.findByRole('link', { name: '查看 CS 5800' });
  await user.click(within(sidebar()).getByRole('link', { name: /培养方案/ }));
  await user.click(within(sidebar()).getByRole('link', { name: /课程对比/ }));
  expect(
    await screen.findByText('课程加载失败（c-cs-5800）：没有找到这门课。'),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole('link', { name: '查看 CS 5800' }),
  ).not.toBeInTheDocument();
  expect(fallback()).toBeEmptyDOMElement();
});

// After a success the failure stays on the query while it is asked again (only a query that never had data goes back
// to pending), so this is the path where the column itself has to tell a retry from the failure.
it('after a definite answer on a later visit, 重新加载 shows the column as loading until its answer', async () => {
  const user = userEvent.setup();
  const third = held();
  const answers = [
    () => json(cs5800.body),
    () => apiError(404, 'not_found', 'Course not found'),
    () => third.response,
  ];
  fakeApi(({ path }) =>
    path === '/course/c-cs-5800' ? answers.shift()!() : catalog({ path }),
  );
  choose('c-cs-5800');
  livePage('/compare');
  await screen.findByRole('link', { name: '查看 CS 5800' });
  await user.click(within(sidebar()).getByRole('link', { name: /培养方案/ }));
  await user.click(within(sidebar()).getByRole('link', { name: /课程对比/ }));
  expect(
    await screen.findByText('课程加载失败（c-cs-5800）：没有找到这门课。'),
  ).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: '重新加载' }));
  await waitFor(() =>
    expect(
      screen.queryByText('课程加载失败（c-cs-5800）：没有找到这门课。'),
    ).not.toBeInTheDocument(),
  );
  expect(screen.getAllByText('正在加载').length).toBeGreaterThan(0);
  third.answer(json(cs5800.body));
  expect(
    await screen.findByRole('link', { name: '查看 CS 5800' }),
  ).toBeInTheDocument();
});

it('the sidebar count follows the list through removal and clear', async () => {
  const user = userEvent.setup();
  fakeApi(catalog);
  choose('c-cs-5800', 'c-cs-6140', 'c-ds-5220', 'c-cs-5100');
  livePage('/compare');
  await screen.findByRole('link', { name: '查看 CS 5100' });
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

it('a removal survives going to another page and back', async () => {
  const user = userEvent.setup();
  fakeApi(catalog);
  choose('c-cs-5800', 'c-cs-6140', 'c-ds-5220', 'c-cs-5100');
  livePage('/compare');
  await screen.findByRole('link', { name: '查看 CS 5100' });
  await user.click(screen.getByRole('button', { name: '移出 CS 6140' }));
  await user.click(screen.getByRole('link', { name: '查看 CS 5800' }));
  await user.click(within(sidebar()).getByRole('link', { name: /课程对比/ }));
  await screen.findByRole('link', { name: '查看 CS 5800' });
  expect(
    screen.queryByRole('button', { name: '移出 CS 6140' }),
  ).not.toBeInTheDocument();
  expect(
    within(screen.getByRole('region', { name: '课程对比内容' })).getByText(
      '已选择 3/4 门；按加入顺序展示，不排名、不判断选课或毕业资格。',
    ),
  ).toBeInTheDocument();
});

it('the live page with four courses has no DOM axe violations', async () => {
  fakeApi(catalog);
  choose('c-cs-5800', 'c-cs-6140', 'c-ds-5220', 'c-cs-5100');
  livePage('/compare');
  await screen.findByRole('link', { name: '查看 CS 5100' });
  const result = await axe(document.body, {
    rules: { 'color-contrast': { enabled: false } },
  });
  expect(result.violations).toEqual([]);
});
