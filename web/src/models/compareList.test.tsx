import { act, renderHook } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import {
  addToCompare,
  clearCompare,
  getCompareList,
  removeFromCompare,
  useCompareList,
} from './compareList';

it('store preserves ID order, prioritises already over full, and never persists or logs', () => {
  const storage = vi.spyOn(Storage.prototype, 'setItem');
  const log = vi.spyOn(console, 'info');
  const { result } = renderHook(() => useCompareList());
  const original = result.current;
  expect(Object.isFrozen(original)).toBe(true);
  act(() => {
    for (const id of ['id-5800', 'id-6140', 'id-5220', 'id-5100'])
      expect(addToCompare(id)).toBe('added');
  });
  expect(result.current).toEqual(['id-5800', 'id-6140', 'id-5220', 'id-5100']);
  expect(original).toEqual([]);
  expect(addToCompare('id-6140')).toBe('already');
  expect(addToCompare('id-fifth')).toBe('full');
  act(() => removeFromCompare('id-6140'));
  expect(result.current).toEqual(['id-5800', 'id-5220', 'id-5100']);
  act(() => {
    expect(addToCompare('id-fifth')).toBe('added');
  });
  expect(result.current).toEqual(['id-5800', 'id-5220', 'id-5100', 'id-fifth']);
  act(() => clearCompare());
  expect(result.current).toEqual([]);
  expect(storage).not.toHaveBeenCalled();
  expect(log).not.toHaveBeenCalled();
});
it('multiple subscribers receive removals and clear; no-op operations keep snapshot identity', () => {
  const a = renderHook(() => useCompareList()),
    b = renderHook(() => useCompareList());
  act(() => {
    addToCompare('a');
    addToCompare('b');
  });
  expect(a.result.current).toEqual(b.result.current);
  const same = getCompareList();
  removeFromCompare('absent');
  expect(addToCompare('a')).toBe('already');
  expect(getCompareList()).toBe(same);
  a.unmount();
  act(() => removeFromCompare('a'));
  expect(b.result.current).toEqual(['b']);
  act(() => clearCompare());
  expect(b.result.current).toEqual([]);
  const empty = getCompareList();
  clearCompare();
  expect(getCompareList()).toBe(empty);
});
