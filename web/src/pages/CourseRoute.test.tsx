import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it } from 'vitest';
import { axe } from 'vitest-axe';
import { addToCompare, getCompareList } from '../models/compareList';
import { apiError, asked, held, json } from '../test/fakeApi';
import type { Call } from '../test/fakeApi';
import { SHARE_NOTE, notFound } from './CourseRoute';
import {
  chats,
  courses,
  identity,
  page,
  stateOf,
  where,
  world,
} from './searchRouteTestUtils';

// What the course page itself asked: the search column beside it asks for its landing.
const own = (calls: readonly Call[]) =>
  calls
    .filter(
      (call) =>
        call.path === '/resolve/course' || call.path.startsWith('/course/'),
    )
    .map(asked);
const heading = (name: string) => screen.findByRole('heading', { name });
const detail = () => screen.getByRole('region', { name: '课程详情' });
const LOOKUP_FAILED = /^链接里的课程暂时打不开。/;

it('the address’s code is looked up, and the first course it names is shown from one GET /course/{id}', async () => {
  const api = world();
  page('/course/CS-6140');
  expect(await heading('Machine Learning')).toBeInTheDocument();
  expect(own(api.calls)).toEqual([
    'GET /resolve/course?ref=CS-6140',
    'GET /course/c-cs-6140',
  ]);
  // R3a's requisites panel is inside, from the same answer.
  expect(
    within(detail()).getByRole('region', { name: '课程先修要求' }),
  ).toBeInTheDocument();
  expect(screen.getByRole('link', { name: '回到课程搜索' })).toHaveAttribute(
    'href',
    '/',
  );
});

it('says it is looking the code up, then loading the detail', async () => {
  world();
  page('/course/CS-6140');
  expect(screen.getByText('正在查找 CS 6140…')).toBeInTheDocument();
  expect(await screen.findByText('正在加载课程详情…')).toBeInTheDocument();
  expect(await heading('Machine Learning')).toBeInTheDocument();
});

it('a link inside the site hands the course ID along: no lookup', async () => {
  const api = world();
  page({ pathname: '/course/CS-6140', state: { courseId: 'c-cs-6140' } });
  expect(await heading('Machine Learning')).toBeInTheDocument();
  expect(own(api.calls)).toEqual(['GET /course/c-cs-6140']);
});

it.each([
  ['an ID that is not text', { courseId: 5 }],
  ['an empty ID', { courseId: '' }],
  ['something else', 'c-cs-6140'],
])(
  'state with %s is not a course ID: the code is looked up',
  async (_name, state) => {
    const api = world();
    page({ pathname: '/course/CS-6140', state });
    expect(await heading('Machine Learning')).toBeInTheDocument();
    expect(own(api.calls)[0]).toBe('GET /resolve/course?ref=CS-6140');
  },
);

it('加入对比 adds the course to the comparison', async () => {
  world();
  page('/course/CS-6140');
  await heading('Machine Learning');
  await userEvent.click(screen.getByRole('button', { name: '加入对比' }));
  expect(getCompareList()).toEqual(['c-cs-6140']);
  expect(screen.getByText('已在对比中（1/4）')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '加入对比' })).toBeDisabled();
});

it('the share box gives the page’s address on the site, spelled from the course’s code', async () => {
  world();
  // However the address spelled it, the link shared is the course's own.
  page('/course/cs6140');
  await heading('Machine Learning');
  await userEvent.click(screen.getByText('分享这门课'));
  const box = screen.getByRole('textbox', { name: '这门课的链接' });
  expect(box).toHaveValue('http://127.0.0.1:5173/course/CS-6140');
  expect(box).toHaveAttribute('readonly');
  expect(screen.getByText(SHARE_NOTE)).toBeVisible();
});

it.each([
  ['names no course', () => json({ ref: 'CS-9999', matches: [] })],
  [
    'is refused as too long',
    () => apiError(422, 'invalid_input', 'ref: too long'),
  ],
  ['is not found', () => apiError(404, 'not_found', 'Not found')],
])(
  'an address that %s says so, with nothing to try again',
  async (_name, answer) => {
    const api = world((call) =>
      call.path === '/resolve/course' ? answer() : undefined,
    );
    page('/course/CS-9999');
    expect(await screen.findByText(notFound('CS 9999'))).toBeInTheDocument();
    expect(
      within(screen.getByRole('main')).queryByRole('button', {
        name: '重新加载',
      }),
    ).not.toBeInTheDocument();
    expect(own(api.calls)).toEqual(['GET /resolve/course?ref=CS-9999']);
  },
);

it('a lookup that fails for a moment says so and can be tried again', async () => {
  let down = true;
  const api = world((call) =>
    call.path === '/resolve/course' && down
      ? apiError(503, 'service_unavailable', 'down')
      : undefined,
  );
  page('/course/CS-6140');
  expect(await screen.findByText(LOOKUP_FAILED)).toHaveTextContent(
    '链接里的课程暂时打不开。服务暂不可用，请稍后手动重试。',
  );
  down = false;
  await userEvent.click(screen.getByRole('button', { name: '重新加载' }));
  expect(await heading('Machine Learning')).toBeInTheDocument();
  expect(api.count('GET', '/resolve/course')).toBe(2);
});

// TanStack keeps a query that once had data in its error state while it tries again: a lookup or a detail asked again
// after a definite failure (a refresh, say) is loading until its answer comes, not failed.
it('a lookup asked again after a definite failure says it is looking until the answer comes', async () => {
  let lookup: 'ok' | 'gone' | 'held' = 'ok';
  const later = held();
  world((call) =>
    call.path !== '/resolve/course' || lookup === 'ok'
      ? undefined
      : lookup === 'gone'
        ? apiError(404, 'not_found', 'Not found')
        : later.response,
  );
  const { client } = page('/course/CS-6140');
  expect(await heading('Machine Learning')).toBeInTheDocument();
  lookup = 'gone';
  await act(() => client.invalidateQueries({ queryKey: ['resolve'] }));
  expect(await screen.findByText(notFound('CS 6140'))).toBeInTheDocument();
  lookup = 'held';
  act(() => {
    void client.invalidateQueries({ queryKey: ['resolve'] });
  });
  expect(await screen.findByText('正在查找 CS 6140…')).toBeInTheDocument();
  expect(screen.queryByText(notFound('CS 6140'))).toBeNull();
  later.answer(json({ ref: 'CS-6140', matches: [identity(courses[0]!)] }));
  expect(await heading('Machine Learning')).toBeInTheDocument();
});

it('a detail asked again after a definite failure says it is loading until the answer comes', async () => {
  let detail: 'ok' | 'gone' | 'held' = 'ok';
  const later = held();
  world((call) =>
    call.path !== '/course/c-cs-6140' || detail === 'ok'
      ? undefined
      : detail === 'gone'
        ? apiError(404, 'not_found', 'Course not found')
        : later.response,
  );
  const { client } = page({
    pathname: '/course/CS-6140',
    state: { courseId: 'c-cs-6140' },
  });
  expect(await heading('Machine Learning')).toBeInTheDocument();
  detail = 'gone';
  await act(() => client.invalidateQueries({ queryKey: ['course'] }));
  expect(
    await screen.findByText('找不到这门课的详情，可能已经下线。'),
  ).toBeInTheDocument();
  detail = 'held';
  act(() => {
    void client.invalidateQueries({ queryKey: ['course'] });
  });
  expect(await screen.findByText('正在加载课程详情…')).toBeInTheDocument();
  expect(screen.queryByText('找不到这门课的详情，可能已经下线。')).toBeNull();
  later.answer(json(courses[0]));
  expect(await heading('Machine Learning')).toBeInTheDocument();
});

it('a code that names several courses opens the first and offers three of the others, each by its ID', async () => {
  const [first, ...rest] = courses;
  const api = world((call) =>
    call.path === '/resolve/course'
      ? json({ ref: 'CS-6140', matches: [first!, ...rest].map(identity) })
      : undefined,
  );
  page('/course/CS-6140');
  await heading('Machine Learning');
  const others = screen.getByRole('group', {
    name: '同一个课号的其他课程',
  });
  expect(others).toHaveTextContent(
    '「CS 6140」对应多门课程，已打开 CS 6140；其他：',
  );
  expect(
    within(others)
      .getAllByRole('button')
      .map((button) => button.textContent),
  ).toEqual([
    'CS 5800 · Algorithms',
    'DS 5220 · Supervised Machine Learning and Learning Theory',
    'CS 7800 · Advanced Algorithms',
  ]);
  await userEvent.click(
    within(others).getByRole('button', {
      name: 'CS 7800 · Advanced Algorithms',
    }),
  );
  expect(where()).toBe('/course/CS-7800');
  expect(stateOf()).toEqual({ courseId: 'c-cs-7800' });
  expect(await heading('Advanced Algorithms')).toBeInTheDocument();
  expect(
    screen.queryByRole('group', { name: '同一个课号的其他课程' }),
  ).not.toBeInTheDocument();
  expect(own(api.calls)).toEqual([
    'GET /resolve/course?ref=CS-6140',
    'GET /course/c-cs-6140',
    'GET /course/c-cs-7800',
  ]);
});

it.each([
  [
    404,
    () => apiError(404, 'not_found', 'Course not found'),
    '找不到这门课的详情，可能已经下线。',
    false,
  ],
  [
    503,
    () => apiError(503, 'service_busy', 'busy'),
    '无法加载课程详情。服务正忙，请稍后手动重试。',
    true,
  ],
])('a detail that answers %s says so', async (_status, answer, text, retry) => {
  let failing = true;
  const api = world((call) =>
    call.path === '/course/c-cs-6140' && failing ? answer() : undefined,
  );
  page('/course/CS-6140');
  expect(await screen.findByText(text)).toBeInTheDocument();
  const button = within(screen.getByRole('main')).queryByRole('button', {
    name: '重新加载',
  });
  expect(button !== null).toBe(retry);
  if (button) {
    failing = false;
    await userEvent.click(button);
    expect(await heading('Machine Learning')).toBeInTheDocument();
    expect(api.count('GET', '/course/c-cs-6140')).toBe(2);
    // The code was looked up once.
    expect(api.count('GET', '/resolve/course')).toBe(1);
  }
});

it('a course the requisites name opens its page by its code', async () => {
  const api = world();
  page('/course/CS-7800');
  await heading('Advanced Algorithms');
  const view = screen
    .getAllByRole('button', { name: '查看' })
    .find((button) => button.dataset.opens === 'CS 5800')!;
  await userEvent.click(view);
  expect(where()).toBe('/course/CS-5800');
  expect(stateOf()).toBeNull();
  expect(await heading('Algorithms')).toBeInTheDocument();
  expect(own(api.calls)).toEqual([
    'GET /resolve/course?ref=CS-7800',
    'GET /course/c-cs-7800',
    'GET /resolve/course?ref=CS-5800',
    'GET /course/c-cs-5800',
  ]);
});

it('what the address names is said back on one line, without backticks, at most 64 characters; it is looked up as it is', async () => {
  const segment = '`CS`　　' + 'X'.repeat(100);
  const api = world((call) =>
    call.path === '/resolve/course'
      ? json({ ref: segment, matches: [] })
      : undefined,
  );
  page(`/course/${encodeURIComponent(segment)}`);
  const label = 'CS ' + 'X'.repeat(61);
  expect(screen.getByText(`正在查找 ${label}…`)).toBeInTheDocument();
  expect(await screen.findByText(notFound(label))).toBeInTheDocument();
  const lookup = api.calls.find((call) => call.path === '/resolve/course')!;
  expect(new URLSearchParams(lookup.search).get('ref')).toBe(segment);
});

it('from the comparison, 查看 opens that course by its ID', async () => {
  const api = world();
  act(() => {
    addToCompare('c-cs-5800');
  });
  page('/compare');
  await userEvent.click(
    await screen.findByRole('link', { name: '查看 CS 5800' }),
  );
  expect(where()).toBe('/course/CS-5800');
  expect(stateOf()).toEqual({ courseId: 'c-cs-5800' });
  expect(await heading('Algorithms')).toBeInTheDocument();
  expect(api.count('GET', '/resolve/course')).toBe(0);
});

it('the conversation stays beside a course and after it', async () => {
  const api = world();
  page('/');
  await userEvent.type(
    screen.getByRole('textbox', { name: '课程问题' }),
    'CS 6140 讲什么？{Enter}',
  );
  await screen.findByRole('group', { name: '接着问' });
  await userEvent.click(screen.getByRole('button', { name: '查看 CS 6140' }));
  expect(await heading('Machine Learning')).toBeInTheDocument();
  expect(
    screen.getByRole('region', { name: '第 1 轮问答' }),
  ).toBeInTheDocument();
  await userEvent.click(screen.getByRole('link', { name: '回到课程搜索' }));
  expect(where()).toBe('/');
  expect(
    screen.getByRole('region', { name: '第 1 轮问答' }),
  ).toBeInTheDocument();
  expect(chats(api.calls)).toHaveLength(1);
  // The landing's Co-op rows are not asked again for a page that shows the conversation.
  expect(api.count('GET', '/coop')).toBe(1);
});

it('a question asked on a course page goes to the search page, where the conversation is', async () => {
  const api = world();
  page('/course/CS-6140');
  await heading('Machine Learning');
  await userEvent.type(
    screen.getByRole('textbox', { name: '课程问题' }),
    'CS 6140 讲什么？{Enter}',
  );
  await waitFor(() => expect(where()).toBe('/'));
  expect(
    await screen.findByRole('group', { name: '接着问' }),
  ).toBeInTheDocument();
  expect(chats(api.calls)).toHaveLength(1);
  expect(screen.queryByRole('region', { name: '课程详情' })).toBeNull();
});

it('has no DOM axe violations with a course open, the others offered and the search column beside it', async () => {
  world((call) =>
    call.path === '/resolve/course'
      ? json({ ref: 'CS-6140', matches: courses.slice(0, 3).map(identity) })
      : undefined,
  );
  const { container } = page('/course/CS-6140');
  await heading('Machine Learning');
  await screen.findByRole('button', { name: '查看 CS 5010' });
  const result = await axe(container, {
    rules: { 'color-contrast': { enabled: false } },
  });
  expect(result.violations).toEqual([]);
  expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
});
