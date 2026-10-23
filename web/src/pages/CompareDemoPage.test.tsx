import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import { App } from '../App';
import { clearCompare, getCompareList } from '../models/compareList';
function page(path = '/compare') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
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
    page(`/compare?case=${name}`);
    expect(getCompareList()).toHaveLength(count);
    expect(screen.queryAllByRole('columnheader')).toHaveLength(
      count ? count + 1 : 0,
    );
  },
);
it('unknown case safely falls back to four synthetic IDs', () => {
  page('/COMPARE/?case=unknown');
  expect(getCompareList()).toEqual([
    'c-cs-5800',
    'c-cs-6140',
    'c-ds-5220',
    'c-cs-5100',
  ]);
});
it('returning to a cleared session never resurrects demo IDs', async () => {
  const user = userEvent.setup();
  page();
  await user.click(screen.getByRole('button', { name: '清空对比' }));
  await user.click(screen.getByRole('link', { name: '回到课程搜索' }));
  await user.click(screen.getByRole('link', { name: /课程对比/ }));
  expect(getCompareList()).toEqual([]);
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
});
it('an external auth-style clear stays cleared without changing the case', () => {
  page();
  act(() => clearCompare());
  expect(getCompareList()).toEqual([]);
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
});
it('failed reload affects only failed columns for 400ms and cancels on case change', async () => {
  vi.useFakeTimers();
  try {
    page('/compare?case=failed');
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
