import { StrictMode } from 'react';
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { axe } from 'vitest-axe';
import PlanDraftDemoPage from './PlanDraftDemoPage';
import { draftDelay, draftOptions } from '../fixtures/draftDemo';
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
      <MemoryRouter initialEntries={['/programs-draft-demo' + query]}>
        <PlanDraftDemoPage />
      </MemoryRouter>
    </StrictMode>,
  );
}
const tick = async (ms: number) => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
};
const result = () => screen.getByRole('status', { name: '选课草案演示结果' });
const checking = () => screen.queryByText('正在核对课程…');
const count = () => screen.queryByText(/^已填 \d+\/20 门/);

describe('options', () => {
  it('only known scenes and speeds are taken; anything else goes back to the defaults', () => {
    expect(draftOptions(new URLSearchParams())).toEqual({
      scenario: 'standard-mixed',
      speed: 'normal',
    });
    for (const name of ['unknown', 'constructor', '__proto__', 'toString', ''])
      expect(
        draftOptions(new URLSearchParams({ scenario: name, speed: 'fast' })),
      ).toEqual({ scenario: 'standard-mixed', speed: 'normal' });
    expect(
      draftOptions(
        new URLSearchParams({ scenario: 'standard-404', speed: 'forever' }),
      ),
    ).toEqual({ scenario: 'standard-404', speed: 'forever' });
  });
  it('the check takes 300 ms, four times that when slow, none when instant, forever never', () => {
    expect(draftDelay('normal')).toBe(300);
    expect(draftDelay('slow')).toBe(1200);
    expect(draftDelay('instant')).toBe(0);
    expect(draftDelay('forever')).toBeNull();
  });
  it('the page shows the scene and speed it was opened with', () => {
    page('?scenario=standard-422&speed=slow');
    expect(screen.getByLabelText('场景')).toHaveValue('standard-422');
    expect(screen.getByLabelText('速度')).toHaveValue('slow');
    expect(
      screen.getAllByRole('option', {
        name: /^standard-|^align-|^older-|^ds-|^bridge-/,
      }),
    ).toHaveLength(29);
  });
  it('the speeds read 正常, 慢, 立即 and 一直加载, in that order', () => {
    page();
    expect(
      [...screen.getByLabelText('速度').querySelectorAll('option')].map((o) => [
        o.value,
        o.textContent,
      ]),
    ).toEqual([
      ['normal', '正常'],
      ['slow', '慢'],
      ['instant', '立即'],
      ['forever', '一直加载'],
    ]);
  });
});

describe('a run of a scene', () => {
  it.each([
    ['normal', 300],
    ['slow', 1200],
    ['instant', 0],
  ] as const)(
    'at %s speed the first check is on its way, then the scene arrives at %i ms',
    async (speed, delay) => {
      vi.useFakeTimers();
      page(`?speed=${speed}`);
      expect(checking()).toBeInTheDocument();
      expect(count()).toBeNull();
      if (delay > 0) await tick(delay - 1);
      expect(checking()).toBeInTheDocument();
      await tick(1);
      expect(checking()).toBeNull();
      expect(count()).toHaveTextContent('已填 7/20 门');
    },
  );
  it('forever never brings the scene and sets no timer', async () => {
    vi.useFakeTimers();
    page('?speed=forever');
    expect(vi.getTimerCount()).toBe(0);
    await tick(60000);
    expect(checking()).toBeInTheDocument();
    expect(count()).toBeNull();
  });
  it('a scene that is itself checking stays checking, with its last answer below', async () => {
    vi.useFakeTimers();
    page('?scenario=standard-checking-again');
    await tick(300);
    expect(checking()).toBeInTheDocument();
    expect(count()).toHaveTextContent('已填 2/20 门');
    await tick(60000);
    expect(checking()).toBeInTheDocument();
  });
  it('a failure scene shows no failure while its first check is on its way', async () => {
    vi.useFakeTimers();
    page('?scenario=standard-404');
    expect(checking()).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
    await tick(300);
    expect(screen.getByRole('alert')).toHaveTextContent(
      '找不到这个培养方案或方案，草案没有计算。',
    );
  });
  it('a failure scene brings its failure and its retry', async () => {
    page('?scenario=standard-409-unavailable&speed=instant');
    expect(
      await screen.findByText(
        '暂时无法核对所选方案，草案没有计算；请稍后重新核对。',
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '重新核对' })).toBeVisible();
  });
  it('the plan line above the draft is R4a’s scope label, also for a plan the draft does not show', async () => {
    page('?scenario=ds-mixed&speed=instant');
    expect(
      screen.getByRole('heading', {
        level: 2,
        name: 'boston · Catalog 2026-2027 · 普通 MS · Synthetic AI concentration',
      }),
    ).toBeInTheDocument();
    cleanup();
    page('?scenario=bridge-not-checked&speed=instant');
    expect(
      screen.getByRole('heading', { level: 2, name: /Bridge/ }),
    ).toBeInTheDocument();
    await act(async () => {});
    expect(screen.queryByRole('heading', { level: 3 })).toBeNull();
    expect(screen.queryByRole('button', { name: '加入草案' })).toBeNull();
  });
});

describe('changing a control starts over', () => {
  it('a new scene or speed shows the first check again and never the earlier answer', async () => {
    vi.useFakeTimers();
    page('?scenario=standard-mixed');
    await tick(300);
    expect(count()).toHaveTextContent('已填 7/20 门');
    fireEvent.change(screen.getByLabelText('场景'), {
      target: { value: 'standard-full' },
    });
    expect(checking()).toBeInTheDocument();
    expect(count()).toBeNull();
    await tick(300);
    expect(count()).toHaveTextContent('已填 20/20 门');
    fireEvent.change(screen.getByLabelText('速度'), {
      target: { value: 'forever' },
    });
    expect(count()).toBeNull();
    await tick(5000);
    expect(count()).toBeNull();
    expect(checking()).toBeInTheDocument();
  });
  it('changing one control keeps the other', () => {
    page('?scenario=standard-404&speed=forever');
    fireEvent.change(screen.getByLabelText('场景'), {
      target: { value: 'standard-422' },
    });
    expect(screen.getByLabelText('速度')).toHaveValue('forever');
    fireEvent.change(screen.getByLabelText('速度'), {
      target: { value: 'slow' },
    });
    expect(screen.getByLabelText('场景')).toHaveValue('standard-422');
  });
  it('the typed text and the last sentence do not survive a new scene', async () => {
    page('?speed=instant');
    await screen.findByText(/^已填 7\/20 门/);
    const box = screen.getByLabelText(/^课号/);
    fireEvent.change(box, { target: { value: 'CS 6140' } });
    await userEvent.click(screen.getByRole('button', { name: '加入草案' }));
    expect(result()).toHaveTextContent('演示：加入「CS 6140」');
    fireEvent.change(screen.getByLabelText('场景'), {
      target: { value: 'standard-add' },
    });
    expect(screen.getByLabelText(/^课号/)).toHaveValue('');
    expect(result()).toBeEmptyDOMElement();
  });
});

describe('the callbacks only say what the real page would do', () => {
  it('each button writes its sentence and the answer stays as it was', async () => {
    page('?speed=instant');
    await screen.findByText(/^已填 7\/20 门/);
    const box = screen.getByLabelText(/^课号/);
    fireEvent.change(box, { target: { value: ' CS 7140,\nzz ' } });
    await userEvent.click(screen.getByRole('button', { name: '加入草案' }));
    expect(result().textContent).toBe('演示：加入「 CS 7140,\nzz 」');
    await userEvent.click(screen.getByRole('button', { name: '移除 CS 5010' }));
    expect(result().textContent).toBe('演示：移除 c-cs-5010');
    await userEvent.click(
      screen.getByRole('button', { name: 'CS 6140 · 课程页／年度先修' }),
    );
    expect(result().textContent).toBe('演示：这里会打开 c-cs-6140');
    await userEvent.click(screen.getByRole('button', { name: '清空草案' }));
    expect(result().textContent).toBe('演示：清空草案');
    expect(box).toHaveValue('');
    expect(count()).toHaveTextContent('已填 7/20 门');
    expect(
      screen.getByText('CS 5010 · Programming Design Paradigm · 4 学分'),
    ).toBeInTheDocument();
  });
  it('retry writes its sentence and the failure stays', async () => {
    page('?scenario=standard-503-transport&speed=instant');
    await userEvent.click(
      await screen.findByRole('button', { name: '重新核对' }),
    );
    expect(result().textContent).toBe('演示：重新核对');
    expect(screen.getByRole('alert')).toHaveTextContent('无法核对草案。');
  });
  it('while the first check is on its way, add says nothing', async () => {
    page('?speed=forever');
    await userEvent.click(screen.getByRole('button', { name: '加入草案' }));
    expect(result()).toBeEmptyDOMElement();
  });
});

it('the demo page after the check has no axe violations', async () => {
  const { container } = page('?scenario=standard-notices&speed=instant');
  await screen.findByText(/^已填 2\/20 门/);
  expect(
    (
      await axe(container, {
        rules: { 'color-contrast': { enabled: false } },
      })
    ).violations,
  ).toEqual([]);
});

it.each(['/programs-draft-demo', '/PROGRAMS-DRAFT-DEMO/'])(
  'whole App at %s uses the offline shell: no API session requests or prefilled cache',
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
    expect(await screen.findByText(/^已填 7\/20 门/)).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      '选课草案演示',
    );
    expect(document.title).toBe('选课草案演示 · NEU-Compass');
    expect(client.getQueryCache().getAll()).toEqual([]);
    expect(fetch).not.toHaveBeenCalled();
    expect(
      screen.getAllByRole('button', { name: '用 NEU 邮箱登录' })[0],
    ).toBeDisabled();
  },
);
