import { StrictMode } from 'react';
import {
  act,
  fireEvent,
  render,
  screen,
  cleanup,
  renderHook,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, it, expect, vi } from 'vitest';
import ProgramsDemoPage from './ProgramsDemoPage';
import { programsOptions } from '../fixtures/programsDemo';
import { PLAN_PLACEHOLDER } from '../models/programFormat';
import { useProgramDemoLoad } from '../features/programs/useProgramDemoLoad';
import { createQueryClient } from '../api/queries';
import { WithApi } from '../test/withApi';
import { App } from '../App';
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});
function page(query = '') {
  return render(
    <StrictMode>
      <MemoryRouter initialEntries={['/programs-demo' + query]}>
        <ProgramsDemoPage />
      </MemoryRouter>
    </StrictMode>,
  );
}
const tick = async (ms: number) => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
};
async function choose(name: string | RegExp) {
  await userEvent.click(
    screen.getByRole('combobox', { name: /选择目录版本与路径/ }),
  );
  await userEvent.click(await screen.findByRole('option', { name }));
}
it('options only accept known own scenarios and speeds', () => {
  expect(programsOptions(new URLSearchParams())).toEqual({
    scenario: 'list',
    speed: 'normal',
  });
  for (const name of ['unknown', 'constructor', '__proto__', 'toString'])
    expect(
      programsOptions(new URLSearchParams({ scenario: name, speed: 'other' })),
    ).toEqual({ scenario: 'list', speed: 'normal' });
  expect(
    programsOptions(
      new URLSearchParams({ scenario: 'cs-standard-ready', speed: 'slow' }),
    ),
  ).toEqual({ scenario: 'cs-standard-ready', speed: 'slow' });
});
it.each([
  ['normal', 300],
  ['slow', 1200],
  ['instant', 0],
] as const)('the %s read completes at exactly %i ms', (speed, delay) => {
  vi.useFakeTimers();
  const { result } = renderHook(() => useProgramDemoLoad('programs', speed), {
    wrapper: StrictMode,
  });
  expect(result.current?.status).toBe('loading');
  if (delay > 0) act(() => vi.advanceTimersByTime(delay - 1));
  expect(result.current?.status).toBe('loading');
  act(() => vi.advanceTimersByTime(delay > 0 ? 1 : 0));
  expect(result.current?.status).toBe('ready');
});
// Every render is recorded: a hook that resets in an effect would render the earlier result once before loading.
it.each([
  ['name', { name: 'failure-503-transport' }, 300, 'failed'],
  ['speed', { speed: 'slow' }, 1200, 'ready'],
  ['request', { request: 1 }, 300, 'ready'],
] as const)(
  'a new %s reads again from loading and no render shows the earlier result',
  (_, change, delay, status) => {
    vi.useFakeTimers();
    const first = { name: 'programs', speed: 'normal', request: 0 };
    const seen: (string | undefined)[] = [];
    const { result, rerender } = renderHook(
      (p: { name: string; speed: string; request: number }) => {
        const load = useProgramDemoLoad(p.name, p.speed, p.request);
        seen.push(load?.status);
        return load;
      },
      { initialProps: first },
    );
    act(() => vi.advanceTimersByTime(300));
    expect(result.current?.status).toBe('ready');
    seen.length = 0;
    rerender({ ...first, ...change });
    expect(seen).not.toContain('ready');
    expect(result.current?.status).toBe('loading');
    act(() => vi.advanceTimersByTime(delay - 1));
    expect(result.current?.status).toBe('loading');
    act(() => vi.advanceTimersByTime(1));
    expect(result.current?.status).toBe(status);
  },
);
it('forever schedules nothing, unmount cancels pending timers and StrictMode does not duplicate work', () => {
  vi.useFakeTimers();
  const { unmount } = renderHook(
    () => useProgramDemoLoad('programs', 'normal'),
    { wrapper: StrictMode },
  );
  expect(vi.getTimerCount()).toBe(1);
  unmount();
  expect(vi.getTimerCount()).toBe(0);
  const next = renderHook(() => useProgramDemoLoad('programs', 'forever'));
  expect(vi.getTimerCount()).toBe(0);
  act(() => vi.advanceTimersByTime(10000));
  expect(next.result.current?.status).toBe('loading');
});
it('scenario and speed changes reset the whole session and stale read results cannot reappear', async () => {
  vi.useFakeTimers();
  page('?scenario=cs-standard-ready');
  fireEvent.change(screen.getByLabelText('场景'), {
    target: { value: 'list-empty' },
  });
  await tick(300);
  expect(screen.getByText('暂时还没有可浏览的培养方案。')).toBeInTheDocument();
  expect(screen.queryByLabelText('项目课程表')).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('场景'), {
    target: { value: 'cs-standard-ready' },
  });
  await tick(300);
  expect(document.querySelector('pre')).not.toBeNull();
  fireEvent.change(screen.getByLabelText('速度'), {
    target: { value: 'forever' },
  });
  expect(document.querySelector('pre')).toBeNull();
  expect(screen.getByText('正在加载课程表…')).toBeInTheDocument();
  await tick(5000);
  expect(document.querySelector('pre')).toBeNull();
});
it('interactive list opens a project, policies follow selection, refresh clears and back restores the list', async () => {
  page('?speed=instant');
  await userEvent.click(
    await screen.findByRole('button', { name: '查看 CS 的课程表' }),
  );
  await screen.findByRole('combobox', { name: /选择目录版本与路径/ });
  expect(
    screen.getByRole('combobox', { name: /选择目录版本与路径/ }),
  ).toHaveTextContent(PLAN_PLACEHOLDER);
  await choose(/2026-2027 · 普通 MS/);
  expect(await screen.findAllByText('官方政策来源')).toHaveLength(2);
  await choose(/2026-2027 · Align/);
  expect(
    await screen.findByText(
      '该精确方案尚无政策证据关联；不能套用其他年度、方向或路径。',
    ),
  ).toBeInTheDocument();
  expect(screen.queryAllByText('官方政策来源')).toHaveLength(0);
  await choose(/2026-2027 · Bridge/);
  expect(
    await screen.findByText('该方案尚未完成来源对照，未显示关联政策证据。'),
  ).toBeInTheDocument();
  await choose(/2025-2026 · 普通 MS/);
  expect(
    await screen.findByText(
      '方案范围或内容版本已变化，政策关联须重新核对；未显示旧证据。',
    ),
  ).toBeInTheDocument();
  await choose(PLAN_PLACEHOLDER);
  expect(document.querySelector('pre')).toBeNull();
  await choose(/2026-2027 · 普通 MS/);
  await screen.findAllByText('官方政策来源');
  await userEvent.click(screen.getByRole('button', { name: '查看 CS 5010' }));
  expect(
    screen.getByRole('status', { name: '培养方案演示结果' }).textContent,
  ).toBe('演示：这里会打开 c-cs-5010');
  await userEvent.click(
    screen.getByRole('button', { name: '刷新方案及政策证据' }),
  );
  await screen.findByRole('combobox', { name: /选择目录版本与路径/ });
  expect(
    screen.getByRole('combobox', { name: /选择目录版本与路径/ }),
  ).toHaveTextContent(PLAN_PLACEHOLDER);
  expect(document.querySelector('pre')).toBeNull();
  await userEvent.click(screen.getByRole('button', { name: '所有培养方案' }));
  expect(
    await screen.findAllByRole('button', { name: /的课程表/ }),
  ).toHaveLength(4);
  await userEvent.click(
    screen.getByRole('button', { name: '查看 DS 的课程表' }),
  );
  await screen.findByRole('combobox', { name: /选择目录版本与路径/ });
  await choose(/普通 MS/);
  expect(
    await screen.findByText(
      '该精确方案尚无政策证据关联；不能套用其他年度、方向或路径。',
    ),
  ).toBeInTheDocument();
});
it('a scenario-specific policy failure is replayed without silently substituting success', async () => {
  page('?scenario=cs-standard-policies-503&speed=instant');
  expect(
    await screen.findByText(
      '无法加载所选方案的政策证据；未使用旧缓存，方案规则仍可浏览。',
    ),
  ).toBeInTheDocument();
  await choose(/Align/);
  await screen.findByText(
    '该精确方案尚无政策证据关联；不能套用其他年度、方向或路径。',
  );
  await choose(/2026-2027 · 普通 MS/);
  expect(
    await screen.findByText(
      '无法加载所选方案的政策证据；未使用旧缓存，方案规则仍可浏览。',
    ),
  ).toBeInTheDocument();
});
it('retry replays the same failed list from loading without fabricating success', async () => {
  vi.useFakeTimers();
  page('?scenario=list-503');
  await tick(300);
  expect(screen.getByRole('alert')).toHaveTextContent('无法加载培养方案列表。');
  fireEvent.click(screen.getByRole('button', { name: '重新加载' }));
  expect(screen.queryByRole('alert')).toBeNull();
  expect(screen.getByText('正在加载培养方案…')).toBeInTheDocument();
  await tick(300);
  expect(screen.getByRole('alert')).toHaveTextContent('无法加载培养方案列表。');
});
it('refresh replays the curriculum from its loading line', async () => {
  vi.useFakeTimers();
  page('?scenario=cs-standard-ready');
  await tick(300);
  expect(document.querySelector('pre')).not.toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '刷新方案及政策证据' }));
  expect(screen.getByText('正在加载课程表…')).toBeInTheDocument();
  await tick(300);
  expect(
    screen.getByRole('combobox', { name: /选择目录版本与路径/ }),
  ).toHaveTextContent(PLAN_PLACEHOLDER);
});
// Real timers at the slow speed: Radix Select and fake timers do not mix in jsdom.
it('a newly chosen plan starts with its own loading line, never the previous plan’s read', async () => {
  page('?scenario=cs-standard-ready&speed=slow');
  expect(
    await screen.findAllByText('官方政策来源', {}, { timeout: 5000 }),
  ).toHaveLength(2);
  await choose(/2026-2027 · Align/);
  expect(screen.getByText('正在加载政策证据…')).toBeInTheDocument();
  expect(screen.queryByText(/政策响应与当前所选方案/)).toBeNull();
  expect(
    await screen.findByText(
      '该精确方案尚无政策证据关联；不能套用其他年度、方向或路径。',
      {},
      { timeout: 5000 },
    ),
  ).toBeInTheDocument();
}, 20000);
it('choosing the same plan again after the placeholder reads its policies again', async () => {
  page('?scenario=cs-standard-ready&speed=slow');
  expect(
    await screen.findAllByText('官方政策来源', {}, { timeout: 5000 }),
  ).toHaveLength(2);
  await choose(PLAN_PLACEHOLDER);
  await choose(/2026-2027 · 普通 MS/);
  expect(screen.getByText('正在加载政策证据…')).toBeInTheDocument();
  expect(
    await screen.findAllByText('官方政策来源', {}, { timeout: 5000 }),
  ).toHaveLength(2);
}, 20000);
it('the first render takes no focus; opening a program and going back move it to the view now shown', async () => {
  page('?speed=instant');
  const cs = await screen.findByRole('button', { name: '查看 CS 的课程表' });
  expect(document.body).toHaveFocus();
  await userEvent.click(cs);
  expect(screen.getByRole('region', { name: '项目课程表' })).toHaveFocus();
  await userEvent.click(screen.getByRole('button', { name: '所有培养方案' }));
  expect(screen.getByRole('region', { name: '培养方案列表' })).toHaveFocus();
});
it('choosing a plan keeps focus on the select and the same curriculum; only the plan’s own disclosure starts closed', async () => {
  page('?scenario=cs-standard-ready&speed=instant');
  await screen.findAllByText('官方政策来源');
  const region = screen.getByRole('region', { name: '项目课程表' });
  const disclosure = (title: string) =>
    screen.getByText(title).closest('details')!;
  const share = disclosure('分享这个培养方案');
  share.open = true;
  disclosure('来源摘录（非完整页面存档）').open = true;
  await choose(/2026-2027 · Align/);
  expect(
    screen.getByRole('combobox', { name: /选择目录版本与路径/ }),
  ).toHaveFocus();
  expect(screen.getByRole('region', { name: '项目课程表' })).toBe(region);
  expect(share.isConnected && share.open).toBe(true);
  expect(disclosure('来源摘录（非完整页面存档）').open).toBe(false);
});
it('refresh keeps focus on its button while the curriculum replays', async () => {
  page('?scenario=cs-standard-ready&speed=instant');
  const refresh = await screen.findByRole('button', {
    name: '刷新方案及政策证据',
  });
  await userEvent.click(refresh);
  expect(refresh).toHaveFocus();
  expect(
    await screen.findByRole('combobox', { name: /选择目录版本与路径/ }),
  ).toHaveTextContent(PLAN_PLACEHOLDER);
  expect(refresh).toHaveFocus();
});
it('retry moves focus to the list while the same failure replays', async () => {
  page('?scenario=list-503&speed=instant');
  await userEvent.click(
    await screen.findByRole('button', { name: '重新加载' }),
  );
  expect(screen.getByRole('region', { name: '培养方案列表' })).toHaveFocus();
  expect(await screen.findByRole('alert')).toHaveTextContent(
    '无法加载培养方案列表。',
  );
});
it('a failed list takes no focus on its first render, and after retry focus stays on the list once the failure is back', async () => {
  page('?scenario=list-503&speed=instant');
  const retry = await screen.findByRole('button', { name: '重新加载' });
  expect(document.body).toHaveFocus();
  await userEvent.click(retry);
  const list = screen.getByRole('region', { name: '培养方案列表' });
  expect(list).toHaveFocus();
  expect(await screen.findByRole('button', { name: '重新加载' })).not.toBe(
    retry,
  );
  expect(list).toHaveFocus();
});
it('after opening a program from the list, choosing a plan, viewing a course and refreshing keep focus where it was', async () => {
  page('?speed=instant');
  await userEvent.click(
    await screen.findByRole('button', { name: '查看 CS 的课程表' }),
  );
  expect(screen.getByRole('region', { name: '项目课程表' })).toHaveFocus();
  await choose(/2026-2027 · 普通 MS/);
  expect(
    screen.getByRole('combobox', { name: /选择目录版本与路径/ }),
  ).toHaveFocus();
  const course = screen.getByRole('button', { name: '查看 CS 5010' });
  await userEvent.click(course);
  expect(course).toHaveFocus();
  const refresh = screen.getByRole('button', { name: '刷新方案及政策证据' });
  await userEvent.click(refresh);
  expect(refresh).toHaveFocus();
  expect(
    await screen.findByRole('combobox', { name: /选择目录版本与路径/ }),
  ).toHaveTextContent(PLAN_PLACEHOLDER);
  expect(refresh).toHaveFocus();
});
it('the list and the curriculum take focus from the demo but are not Tab stops of their own', async () => {
  page('?speed=instant');
  await userEvent.click(
    await screen.findByRole('button', { name: '查看 CS 的课程表' }),
  );
  await userEvent.tab();
  expect(screen.getByRole('button', { name: '所有培养方案' })).toHaveFocus();
  await userEvent.tab({ shift: true });
  expect(screen.getByLabelText('速度')).toHaveFocus();
  await userEvent.click(screen.getByRole('button', { name: '所有培养方案' }));
  expect(screen.getByRole('region', { name: '培养方案列表' })).toHaveFocus();
  await userEvent.tab();
  expect(
    screen.getByRole('button', { name: '查看 CS 的课程表' }),
  ).toHaveFocus();
  await userEvent.tab({ shift: true });
  expect(screen.getByLabelText('速度')).toHaveFocus();
});
it('moving focus to the view now shown does not scroll the page', async () => {
  page('?speed=instant');
  const cs = await screen.findByRole('button', { name: '查看 CS 的课程表' });
  const focus = vi.spyOn(HTMLElement.prototype, 'focus');
  await userEvent.click(cs);
  expect(focus.mock.contexts.at(-1)).toBe(
    screen.getByRole('region', { name: '项目课程表' }),
  );
  expect(focus.mock.lastCall).toEqual([{ preventScroll: true }]);
});
it('after refresh, choosing the plan read before reads its policies again', async () => {
  page('?scenario=cs-nothing-selected&speed=slow');
  await screen.findByRole(
    'combobox',
    { name: /选择目录版本与路径/ },
    { timeout: 5000 },
  );
  await choose(/2026-2027 · 普通 MS/);
  expect(
    await screen.findAllByText('官方政策来源', {}, { timeout: 5000 }),
  ).toHaveLength(2);
  await userEvent.click(
    screen.getByRole('button', { name: '刷新方案及政策证据' }),
  );
  await screen.findByRole(
    'combobox',
    { name: /选择目录版本与路径/ },
    { timeout: 5000 },
  );
  await choose(/2026-2027 · 普通 MS/);
  expect(screen.getByText('正在加载政策证据…')).toBeInTheDocument();
  expect(
    await screen.findAllByText('官方政策来源', {}, { timeout: 5000 }),
  ).toHaveLength(2);
}, 20000);
it('going back to the list clears the status line', async () => {
  page('?scenario=cs-standard-ready&speed=instant');
  await userEvent.click(
    await screen.findByRole('button', { name: '查看 CS 5010' }),
  );
  const status = screen.getByRole('status', { name: '培养方案演示结果' });
  expect(status).toHaveTextContent('演示：这里会打开 c-cs-5010');
  await userEvent.click(screen.getByRole('button', { name: '所有培养方案' }));
  expect(status).toBeEmptyDOMElement();
});
it.each(['/programs-demo', '/PROGRAMS-DEMO/'])(
  'whole App at %s uses no API session requests or prefilled cache',
  async (path) => {
    const client = createQueryClient();
    render(
      <StrictMode>
        <WithApi client={client}>
          <MemoryRouter initialEntries={[path + '?speed=instant']}>
            <App />
          </MemoryRouter>
        </WithApi>
      </StrictMode>,
    );
    expect(
      await screen.findByRole('button', { name: '查看 CS 的课程表' }),
    ).toBeInTheDocument();
    expect(client.getQueryCache().getAll()).toEqual([]);
    expect(fetch).not.toHaveBeenCalled();
    expect(
      screen.getAllByRole('button', { name: '用 NEU 邮箱登录' })[0],
    ).toBeDisabled();
  },
);
