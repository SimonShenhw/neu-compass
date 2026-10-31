import { StrictMode } from 'react';
import {
  act,
  fireEvent,
  render,
  renderHook,
  screen,
} from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
import SearchLandingDemoPage from './SearchLandingDemoPage';
import { App } from '../App';
import { WithApi } from '../test/withApi';
import { createQueryClient } from '../api/queries';
import type { ChatSource } from '../api/chat';
import { useLandingDemo } from '../features/search-landing/useLandingDemo';
import { LandingDemoConversation } from '../features/search-landing/LandingDemoConversation';
import {
  landingSources,
  landingOptions,
  sampleChat,
} from '../fixtures/landingDemo';
import { SAMPLE_QUESTIONS } from '../models/landing';
import { settledLanding } from '../features/search-landing/landingTestUtils';

afterEach(() => vi.useRealTimers());
const tick = (ms: number) =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
const finish = () =>
  act(async () => {
    await vi.runAllTimersAsync();
  });
const status = () =>
  screen.getByRole('status', { name: '落地页演示结果' }).textContent;
function page(query = '?speed=instant', app = false) {
  return render(
    <StrictMode>
      <WithApi>
        <MemoryRouter initialEntries={['/search-landing-demo' + query]}>
          {app ? <App /> : <SearchLandingDemoPage />}
        </MemoryRouter>
      </WithApi>
    </StrictMode>,
  );
}
it('landing demo URL defaults are independently validated, including prototype-like names', () => {
  expect(landingOptions(new URLSearchParams())).toEqual({
    scenario: 'guest',
    speed: 'normal',
  });
  expect(
    landingOptions(new URLSearchParams('scenario=member-2&speed=forever')),
  ).toEqual({ scenario: 'member-2', speed: 'forever' });
  for (const name of ['unknown', 'toString', 'constructor', '__proto__'])
    expect(
      landingOptions(new URLSearchParams({ scenario: name, speed: 'bad' })),
    ).toEqual({ scenario: 'guest', speed: 'normal' });
});
it('demo sources release programs then curricula, while Co-op is independent, at exact times', async () => {
  vi.useFakeTimers();
  const hook = renderHook(() => useLandingDemo('guest', 'normal'), {
    wrapper: StrictMode,
  });
  expect(hook.result.current.programs.status).toBe('loading');
  await tick(299);
  expect(hook.result.current.programs.status).toBe('loading');
  await tick(1);
  expect(hook.result.current.programs.status).toBe('ready');
  expect(Object.keys(hook.result.current.curricula)).toEqual([]);
  await tick(149);
  expect(hook.result.current.coop.status).toBe('loading');
  await tick(1);
  expect(hook.result.current.coop.status).toBe('ready');
  await tick(149);
  expect(Object.keys(hook.result.current.curricula)).toEqual([]);
  await tick(1);
  expect(
    Object.values(hook.result.current.curricula).map((v) => v.status),
  ).toEqual(['ready', 'ready', 'ready']);
  expect(vi.getTimerCount()).toBe(0);
});
it('slow multiplies all source delays, forever has no scheduled work and unmount cancels late results', async () => {
  vi.useFakeTimers();
  const slow = renderHook(() => useLandingDemo('guest', 'slow'));
  await tick(1199);
  expect(slow.result.current.programs.status).toBe('loading');
  await tick(1);
  expect(slow.result.current.programs.status).toBe('ready');
  await tick(599);
  expect(slow.result.current.coop.status).toBe('loading');
  await tick(1);
  expect(slow.result.current.coop.status).toBe('ready');
  slow.unmount();
  expect(vi.getTimerCount()).toBe(0);
  const forever = renderHook(() => useLandingDemo('guest', 'forever'));
  await tick(100000);
  expect(forever.result.current.programs.status).toBe('loading');
  expect(vi.getTimerCount()).toBe(0);
  forever.unmount();
});
it('instant releases every source with no delay', async () => {
  vi.useFakeTimers();
  const hook = renderHook(() => useLandingDemo('guest', 'instant'));
  await tick(0);
  expect(hook.result.current.programs.status).toBe('ready');
  expect(hook.result.current.coop.status).toBe('ready');
  // A zero delay set during a fake-timer tick runs one fake millisecond later.
  await tick(1);
  expect(Object.keys(hook.result.current.curricula)).toHaveLength(3);
  hook.unmount();
});
it.each(['programs-503', 'programs-malformed', 'no-programs'])(
  'demo %s never schedules irrelevant curricula',
  async (scenario) => {
    vi.useFakeTimers();
    const hook = renderHook(() => useLandingDemo(scenario, 'normal'));
    await tick(300);
    expect(Object.keys(hook.result.current.curricula)).toEqual([]);
    await tick(150);
    expect(vi.getTimerCount()).toBe(0);
    hook.unmount();
  },
);
it('demo sources do not request an unlisted featured curriculum', async () => {
  vi.useFakeTimers();
  const hook = renderHook(() => useLandingDemo('aai-not-listed', 'instant'));
  await finish();
  expect(Object.keys(hook.result.current.curricula)).toEqual([
    'cs-ms',
    'ds-ms',
  ]);
  hook.unmount();
});
it.each([
  ['AAI · 4 门课', '演示：这里会打开培养方案 aai-ms'],
  ['查看 CS 5010', '演示：这里会打开 c-cs-5010'],
  ['去看看', '演示：这里会去 Co-op 页'],
])(
  'landing demo %s writes status without navigation',
  async (button, notice) => {
    vi.useFakeTimers();
    page();
    await finish();
    fireEvent.click(screen.getByRole('button', { name: button }));
    expect(status()).toBe(notice);
    expect(screen.getByLabelText('搜索落地内容')).toBeInTheDocument();
  },
);
it('scenario and speed changes discard old timers and status, retry replays the same synthetic failure', async () => {
  vi.useFakeTimers();
  page('?scenario=guest&speed=slow');
  await tick(1200);
  fireEvent.change(screen.getByRole('combobox', { name: '数据' }), {
    target: { value: 'programs-503' },
  });
  expect(screen.queryByRole('button', { name: 'AAI · 4 门课' })).toBeNull();
  fireEvent.change(screen.getByRole('combobox', { name: '速度' }), {
    target: { value: 'forever' },
  });
  await tick(50000);
  expect(screen.queryByRole('button', { name: '去看看' })).toBeNull();
  fireEvent.change(screen.getByRole('combobox', { name: '速度' }), {
    target: { value: 'instant' },
  });
  await finish();
  expect(screen.getByRole('button', { name: '重新加载' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '去看看' }));
  fireEvent.click(screen.getByRole('button', { name: '重新加载' }));
  expect(screen.getByText('正在加载推荐内容…')).toBeInTheDocument();
  expect(
    screen.getByRole('status', { name: '落地页演示结果' }),
  ).toBeEmptyDOMElement();
  await finish();
  expect(screen.getByRole('button', { name: '重新加载' })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'AAI · 4 门课' })).toBeNull();
});
it.each(SAMPLE_QUESTIONS.map((q, index) => ({ ...q, index })))(
  'sample $label switches immediately to its real R3c synthetic conversation and hands off focus',
  async (q) => {
    vi.useFakeTimers();
    const result = page();
    await finish();
    fireEvent.click(screen.getByRole('button', { name: q.label }));
    expect(screen.queryByLabelText('搜索落地内容')).toBeNull();
    expect(screen.getByLabelText('搜索演示对话')).toHaveFocus();
    expect(
      result.container.querySelector('[data-kind="question"]'),
    ).toHaveTextContent(q.query);
    expect(screen.getByText('正在查找相关的课…')).toBeInTheDocument();
    await finish();
    expect(screen.getByLabelText('回答状态')).toHaveTextContent('回答完成。');
    expect(screen.queryByRole('button', { name: '有帮助' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '回到落地页' }));
    expect(screen.getByLabelText('落地页演示')).toHaveFocus();
    expect(screen.queryByLabelText('搜索演示对话')).toBeNull();
    await finish();
    expect(screen.getByLabelText('搜索落地内容')).toBeInTheDocument();
  },
);
const samplePhrases = [
  '讲算法的设计与分析',
  '适合入门的有',
  '和数据库相关的是',
  '机器学习方向的有',
];
it.each(SAMPLE_QUESTIONS.map((q, index) => ({ ...q, index })))(
  'sample $label plays its own chat sample at normal speed, and its 查看 and follow-up only write status',
  async (q) => {
    vi.useFakeTimers();
    page();
    await finish();
    fireEvent.click(screen.getByRole('button', { name: q.label }));
    await tick(399);
    expect(screen.getByText('正在查找相关的课…')).toBeInTheDocument();
    await finish();
    expect(screen.getByLabelText('搜索演示对话')).toHaveTextContent(
      samplePhrases[q.index]!,
    );
    const first = sampleChat(q.index).events[0] as unknown as {
      meta: { results: { course_id: string }[] };
    };
    fireEvent.click(screen.getAllByRole('button', { name: /^查看 / })[0]!);
    expect(status()).toBe(
      `演示：这里会打开 ${first.meta.results[0]!.course_id}`,
    );
    const followUp = document.querySelector<HTMLButtonElement>(
      '[data-kind="followup"]',
    )!;
    fireEvent.click(followUp);
    expect(status()).toBe(`演示：这里会接着问「${followUp.textContent}」`);
  },
);
it('a refused first turn and a source error never bring landing content back or lose the conversation focus', async () => {
  const source: ChatSource = async function* () {
    yield await Promise.reject({
      status: 429,
      errorType: null,
      retryAfter: 2,
      invalidFields: [],
      reason: null,
    });
  };
  render(
    <LandingDemoConversation
      {...settledLanding(landingSources('guest'))}
      onReset={vi.fn()}
      onOpenProgram={vi.fn()}
      onViewCourse={vi.fn()}
      onOpenCoop={vi.fn()}
      onFollowUp={vi.fn()}
      sourceFor={() => source}
    />,
  );
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'CS 5800' }));
  });
  expect(screen.queryByLabelText('搜索落地内容')).toBeNull();
  expect(screen.getByLabelText('搜索演示对话')).toHaveFocus();
  expect(screen.getByLabelText('回答状态')).toHaveTextContent(
    '请求过于频繁，请2 秒后手动重试。',
  );
});
it('returning during an active chat cancels it and old read/chat results cannot replace the restored landing', async () => {
  vi.useFakeTimers();
  page('?speed=normal');
  fireEvent.click(screen.getByRole('button', { name: 'CS 5800' }));
  await tick(400);
  fireEvent.click(screen.getByRole('button', { name: '回到落地页' }));
  await finish();
  expect(screen.queryByLabelText('搜索演示对话')).toBeNull();
  expect(screen.getAllByLabelText('搜索落地内容')).toHaveLength(1);
});
it.each(['/search-landing-demo', '/SEARCH-LANDING-DEMO/'])(
  'full app demo cold start %s never mounts API session queries even with an empty client',
  async (path) => {
    const client = createQueryClient();
    render(
      <StrictMode>
        <QueryClientProvider client={client}>
          <MemoryRouter initialEntries={[path + '?speed=instant']}>
            <App />
          </MemoryRouter>
        </QueryClientProvider>
      </StrictMode>,
    );
    expect(
      await screen.findByRole('heading', {
        name: '问一门课，或者一个选课问题',
      }),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole('button', { name: 'AAI · 4 门课' }),
    ).toBeInTheDocument();
    expect(client.getQueryCache().getAll()).toHaveLength(0);
    expect(fetch).not.toHaveBeenCalled();
    expect(
      screen.getAllByRole('button', { name: '用 NEU 邮箱登录' })[0],
    ).toBeDisabled();
  },
);
