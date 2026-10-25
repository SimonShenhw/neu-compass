import { useSyncExternalStore } from 'react';

export const MAX_COMPARE_COURSES = 4;

const empty: readonly string[] = Object.freeze([]);

export interface CompareList {
  add: (id: string) => 'added' | 'already' | 'full';
  remove: (id: string) => void;
  clear: () => void;
  get: () => readonly string[];
  subscribe: (listener: () => void) => () => void;
}

// An ordered list of course IDs, at most four, in memory only (R5b). The page's list is the one below; the compare
// demo keeps one of its own, so a demo never changes what the student chose (R5d).
export function createCompareList(): CompareList {
  let ids: readonly string[] = empty;
  const listeners = new Set<() => void>();
  function update(next: readonly string[]) {
    ids = Object.freeze([...next]);
    for (const listener of listeners) listener();
  }
  return {
    add(id) {
      if (ids.includes(id)) return 'already';
      if (ids.length >= MAX_COMPARE_COURSES) return 'full';
      update([...ids, id]);
      return 'added';
    },
    remove(id) {
      if (ids.includes(id)) update(ids.filter((item) => item !== id));
    },
    clear() {
      if (ids.length) update(empty);
    },
    get: () => ids,
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
}

export function useList(list: CompareList): readonly string[] {
  return useSyncExternalStore(list.subscribe, list.get, () => empty);
}

const page = createCompareList();
export const addToCompare = page.add;
export const removeFromCompare = page.remove;
export const clearCompare = page.clear;
export const getCompareList = page.get;
export function useCompareList(): readonly string[] {
  return useList(page);
}
