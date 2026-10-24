import { StrictMode } from 'react';
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, expect, it, vi } from 'vitest';
import { App } from '../App';
import SearchDemoPage from './SearchDemoPage';
import {
  demoFeedback,
  demoOptions,
  demoSource,
  searchFixture,
  searchSequence,
} from '../fixtures/searchDemo';
import { parseReceipt } from '../models/answerFeedback';
import { getCompareList } from '../models/compareList';
import { loadExpected } from '../features/search-answer/searchTestUtils';

afterEach(() => {
  vi.useRealTimers();
});
function Location() {
  return <output aria-label="搜索演示网址">{useLocation().search}</output>;
}
function page(query = '?speed=instant', app = false) {
  return render(
    <StrictMode>
      <MemoryRouter initialEntries={['/search-demo' + query]}>
        {app ? <App /> : <SearchDemoPage />}
        <Location />
      </MemoryRouter>
    </StrictMode>,
  );
}
it('search demo defaults and invalid URL options fall back independently', () => {
  expect(demoOptions(new URLSearchParams())).toEqual({
    caseName: 'alias-cs-6140',
    feedback: 'off',
    reason: 'on',
    vote: 'saved',
    speed: 'normal',
  });
  expect(
    demoOptions(
      new URLSearchParams(
        'case=bad&feedback=bad&reason=bad&vote=bad&speed=bad',
      ),
    ),
  ).toEqual(demoOptions(new URLSearchParams()));
});
it('search demo lazy App route renders one turn under StrictMode without a navigation entry', async () => {
  const { container } = page('?speed=instant', true);
  await screen.findByRole('button', { name: '查看 CS 6140' });
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
    '搜索回答演示',
  );
  expect(screen.queryByRole('link', { name: '搜索回答演示' })).toBeNull();
  await waitFor(() =>
    expect(screen.getByRole('status', { name: '回答状态' })).toHaveTextContent(
      '回答完成。',
    ),
  );
  expect(container.querySelectorAll('[data-kind="question"]')).toHaveLength(1);
  expect(
    screen
      .getByRole('combobox', { name: '演示对话' })
      .querySelectorAll('option'),
  ).toHaveLength(34);
});
it('search demo view and followup only announce, while replay clears state and never touches the real store', async () => {
  const { container } = page();
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: '查看 CS 6140' }));
  expect(
    screen.getByRole('status', { name: '搜索演示结果' }),
  ).toHaveTextContent('演示：这里会打开 c-cs-6140');
  await user.click(
    await screen.findByRole('button', { name: '这门课讲什么内容？' }),
  );
  expect(
    screen.getByRole('status', { name: '搜索演示结果' }),
  ).toHaveTextContent('演示：这里会接着问「这门课讲什么内容？」');
  expect(getCompareList()).toEqual([]);
  expect(container.querySelectorAll('[data-kind="question"]')).toHaveLength(1);
  await user.click(screen.getByRole('button', { name: '开始' }));
  await screen.findByRole('button', { name: '查看 CS 6140' });
  expect(
    screen.getByRole('status', { name: '搜索演示结果' }),
  ).toBeEmptyDOMElement();
  expect(container.querySelectorAll('[data-kind="question"]')).toHaveLength(1);
});
it('search demo says exactly which course it would open', async () => {
  page();
  await userEvent
    .setup()
    .click(await screen.findByRole('button', { name: '查看 CS 6140' }));
  expect(screen.getByRole('status', { name: '搜索演示结果' }).textContent).toBe(
    '演示：这里会打开 c-cs-6140',
  );
});
it('search demo plays the four-turn conversation in the reference order', () => {
  const expected = loadExpected<{ scenarios: { turns: string[] }[] }>(
    'conversation-four-turns.json',
  );
  expect(searchSequence('conversation-four-turns')).toEqual(
    expected.scenarios[0]!.turns,
  );
});
it.each([
  ['回答反馈', 'on'],
  ['409 带 reason', 'off'],
  ['点评价时', '404'],
  ['速度', 'slow'],
  ['演示对话', 'model-error'],
])(
  'search demo changing %s remounts stream, disclosure and callback state',
  async (label, value) => {
    const { container } = page('?speed=instant&keep=1');
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole('button', { name: '查看 CS 6140' }),
    );
    const oldSummary = container.querySelector('summary')!;
    await user.click(oldSummary);
    expect(container.querySelector('details')!.open).toBe(false);
    fireEvent.change(screen.getByRole('combobox', { name: label }), {
      target: { value },
    });
    expect(
      screen.getByRole('status', { name: '搜索演示结果' }),
    ).toBeEmptyDOMElement();
    expect(oldSummary.isConnected).toBe(false);
    expect(
      screen.getByRole('status', { name: '搜索演示网址' }),
    ).toHaveTextContent('keep=1');
  },
);
it('search demo sequences all four turns once and only the last answer gets followups', async () => {
  const { container } = page('?case=conversation-four-turns&speed=instant');
  await waitFor(() =>
    expect(container.querySelectorAll('[data-kind="question"]')).toHaveLength(
      4,
    ),
  );
  await waitFor(() =>
    expect(screen.getByRole('status', { name: '回答状态' })).toHaveTextContent(
      '回答完成。',
    ),
  );
  expect(container.querySelectorAll('[data-kind="followup"]')).toHaveLength(3);
  expect(searchSequence('conversation-followup')).toEqual([
    'alias-cs-6140',
    'context-followup',
  ]);
});
it('search demo shows reason-specific and current-API generic 409 copy without exposing detail', async () => {
  page('?case=refused-409-plan-stale&reason=on&speed=instant');
  expect(
    await screen.findByText(
      '所选方案的范围或内容版本已变化，这个问题还没有回答；方案选择已清除。可以在「方案」里重新选择后再问，或不选方案直接再问。',
      { selector: '[data-kind="failure"]' },
    ),
  ).toBeVisible();
  fireEvent.change(screen.getByRole('combobox', { name: '409 带 reason' }), {
    target: { value: 'off' },
  });
  expect(
    await screen.findByText(
      '这个问题和所选的项目或方案对不上，还没有回答。请检查「项目」和「方案」，或者改写问题后再问。',
      { selector: '[data-kind="failure"]' },
    ),
  ).toBeVisible();
});
it('demo source exact timer schedule, slow multiplier and abort cleanup', async () => {
  vi.useFakeTimers();
  const controller = new AbortController();
  const iterator = demoSource(
    searchFixture('alias-cs-6140'),
    'normal',
    false,
  )(controller.signal)[Symbol.asyncIterator]();
  let resolved = false;
  const first = iterator.next().then((v) => {
    resolved = true;
    return v;
  });
  await vi.advanceTimersByTimeAsync(399);
  expect(resolved).toBe(false);
  await vi.advanceTimersByTimeAsync(1);
  expect((await first).value?.type).toBe('meta');
  resolved = false;
  const second = iterator.next().then((v) => {
    resolved = true;
    return v;
  });
  await vi.advanceTimersByTimeAsync(149);
  expect(resolved).toBe(false);
  await vi.advanceTimersByTimeAsync(1);
  expect((await second).value?.type).toBe('token');
  await iterator.return?.();
  const abort = new AbortController(),
    slow = demoSource(
      searchFixture('alias-cs-6140'),
      'slow',
      true,
    )(abort.signal)[Symbol.asyncIterator]();
  const pending = slow.next();
  const rejected = expect(pending).rejects.toBe('cancel');
  await vi.advanceTimersByTimeAsync(1599);
  abort.abort('cancel');
  await rejected;
  expect(vi.getTimerCount()).toBe(0);
});
it('demo stream switches cleanly while busy and does not apply old delayed output', async () => {
  vi.useFakeTimers();
  const { container } = page('?speed=slow');
  await act(async () => {});
  expect(screen.getByText('正在查找相关的课…')).toBeVisible();
  fireEvent.change(screen.getByRole('combobox', { name: '演示对话' }), {
    target: { value: 'rejected' },
  });
  await act(async () => {
    await vi.runAllTimersAsync();
  });
  expect(container.textContent).not.toContain('Machine Learning');
  expect(container.querySelectorAll('[data-kind="question"]')).toHaveLength(1);
});
it.each(['saved', '404', '503', 'mismatch'] as const)(
  'demo feedback outcome %s conforms to callback contract',
  async (outcome) => {
    const receipt = searchFixture('feedback-receipt').events.find(
      (e) => e.type === 'done',
    );
    if (receipt?.type !== 'done') throw Error('fixture');
    const vote = { ...parseReceipt(receipt.feedback)!, rating: 'up' as const };
    if (outcome === '404' || outcome === '503')
      await expect(demoFeedback(vote, outcome)).rejects.toMatchObject({
        status: Number(outcome),
        reason: null,
      });
    else
      await expect(demoFeedback(vote, outcome)).resolves.toEqual({
        answer_id: vote.answer_id,
        rating: outcome === 'saved' ? 'up' : 'down',
      });
  },
);
