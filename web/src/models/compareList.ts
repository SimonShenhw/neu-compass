import { useSyncExternalStore } from 'react';

export const MAX_COMPARE_COURSES = 4;

const empty: readonly string[] = Object.freeze([]);
let ids: readonly string[] = empty;
const listeners = new Set<() => void>();
function update(next: readonly string[]) {
  ids = Object.freeze([...next]);
  for (const listener of listeners) listener();
}
export function addToCompare(id: string): 'added' | 'already' | 'full' {
  if (ids.includes(id)) return 'already';
  if (ids.length >= MAX_COMPARE_COURSES) return 'full';
  update([...ids, id]);
  return 'added';
}
export function removeFromCompare(id: string) {
  if (ids.includes(id)) update(ids.filter((item) => item !== id));
}
export function clearCompare() {
  if (ids.length) update(empty);
}
const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};
export const getCompareList = () => ids;
export function useCompareList(): readonly string[] {
  return useSyncExternalStore(subscribe, getCompareList, () => empty);
}
