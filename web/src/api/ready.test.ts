import { expect, it } from 'vitest';
import { asked, fakeApi, json } from '../test/fakeApi';
import { expectTimeout } from '../test/timeouts';
import { PUBLIC_FRESH_MS, createQueryClient } from './queries';
import { READY_RETRY_MS, coursesIndexed, readyQuery } from './ready';

it('the course count is GET /ready, the same for everyone and fresh for five minutes, waiting 5 seconds; a failure goes again after 30', async () => {
  expect(readyQuery.queryKey).toEqual(['ready']);
  expect(readyQuery.staleTime).toBe(PUBLIC_FRESH_MS);
  expect(READY_RETRY_MS).toBe(30_000);
  const body = { status: 'ready', courses_indexed: 4321, bm25_corpus: 4321 };
  const api = fakeApi(() => json(body));
  expect(await createQueryClient().fetchQuery(readyQuery)).toEqual(body);
  expect(api.calls.map(asked)).toEqual(['GET /ready']);
  await expectTimeout(
    () => createQueryClient().fetchQuery(readyQuery),
    'quick',
  );
});

it('reads the count only while it is a whole number above 0, as the hero did', () => {
  expect(coursesIndexed({ status: 'ready', courses_indexed: 4321 })).toBe(4321);
  expect(coursesIndexed({ courses_indexed: 1 })).toBe(1);
  for (const body of [
    undefined,
    null,
    [4321],
    '4321',
    {},
    { status: 'warming', courses_indexed: 0, bm25_corpus: 0 },
    { courses_indexed: -1 },
    { courses_indexed: 1.5 },
    { courses_indexed: '4321' },
    { courses_indexed: Number.NaN },
    { courses_indexed: Number.POSITIVE_INFINITY },
    { courses_indexed: 2 ** 53 },
    { courses_indexed: true },
  ])
    expect(coursesIndexed(body), JSON.stringify(body)).toBeNull();
});
