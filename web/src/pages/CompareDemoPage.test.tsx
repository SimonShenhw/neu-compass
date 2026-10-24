import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import { App } from '../App';
import { demoList } from '../fixtures/compareDemo';
import { addToCompare, getCompareList } from '../models/compareList';
import { WithApi } from '../test/withApi';
function page(path = '/compare-demo') {
  return render(
    <WithApi>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </WithApi>,
  );
}
it.each([
  ['four', 4],
  ['one', 1],
  ['empty', 0],
  ['failed', 4],
  ['unrecognised', 3],
  ['bad-cell', 2],
  ['loading', 2],
  ['requisites-unavailable', 1],
] as const)(
  'demo case %s seeds only its intended IDs and columns',
  (name, count) => {
    page(`/compare-demo?case=${name}`);
    expect(demoList.get()).toHaveLength(count);
    expect(screen.queryAllByRole('columnheader')).toHaveLength(
      count ? count + 1 : 0,
    );
  },
);
it('unknown case safely falls back to four synthetic IDs', () => {
  page('/COMPARE-DEMO/?case=unknown');
  expect(demoList.get()).toEqual([
    'c-cs-5800',
    'c-cs-6140',
    'c-ds-5220',
    'c-cs-5100',
  ]);
});
it('returning to a cleared demo never resurrects demo IDs', async () => {
  const user = userEvent.setup();
  const first = page();
  await user.click(screen.getByRole('button', { name: '清空对比' }));
  first.unmount();
  page();
  expect(demoList.get()).toEqual([]);
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
});
it('the demo keeps its own list: the student’s comparison and the sidebar count stay as they were (R5d)', async () => {
  const user = userEvent.setup();
  act(() => {
    addToCompare('c-student-choice');
  });
  page('/compare-demo?case=four');
  expect(demoList.get()).toHaveLength(4);
  expect(getCompareList()).toEqual(['c-student-choice']);
  const nav = screen.getByRole('navigation', { name: '主导航' });
  expect(within(nav).getByRole('link', { name: /课程对比/ })).toHaveTextContent(
    '1',
  );
  await user.click(screen.getByRole('button', { name: '移出 CS 6140' }));
  await user.click(screen.getByRole('button', { name: '清空对比' }));
  expect(demoList.get()).toEqual([]);
  expect(getCompareList()).toEqual(['c-student-choice']);
});
it('failed reload affects only failed columns for 400ms and cancels on case change', async () => {
  vi.useFakeTimers();
  try {
    page('/compare-demo?case=failed');
    expect(screen.getAllByText('加载失败')).toHaveLength(14);
    fireEvent.click(screen.getByRole('button', { name: '重新加载' }));
    expect(screen.getAllByText('正在加载')).toHaveLength(16);
    expect(
      screen.getByRole('link', { name: '查看 CS 5800' }),
    ).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(399);
    });
    expect(
      screen.queryByRole('button', { name: '重新加载' }),
    ).not.toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(screen.getAllByText('加载失败')).toHaveLength(14);
    fireEvent.click(screen.getByRole('button', { name: '重新加载' }));
    fireEvent.change(screen.getByRole('combobox', { name: '演示场景' }), {
      target: { value: 'one' },
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(400);
    });
    expect(
      screen.getByRole('link', { name: '查看 CS 7800' }),
    ).toBeInTheDocument();
    expect(screen.queryByText('加载失败')).not.toBeInTheDocument();
  } finally {
    vi.useRealTimers();
  }
});
