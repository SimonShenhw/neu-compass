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
    screen.getByRole('status', { name: '培养方案演示结果' }),
  ).toHaveTextContent('演示：这里会打开 c-cs-5010');
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
