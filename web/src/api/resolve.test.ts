import type { QueryClient } from '@tanstack/react-query';
import { expect, it } from 'vitest';
import { ApiError } from './client';
import { createQueryClient } from './queries';
import { parseResolved, resolveQuery } from './resolve';
import { asked, fakeApi, json } from '../test/fakeApi';
import { expectTimeout } from '../test/timeouts';

const match = {
  course_id: 'c-cs-5800',
  primary_code: 'CS 5800',
  primary_name: 'Algorithms',
};

it('reads the matches, most specific first, and keeps only their three fields', () => {
  expect(
    parseResolved({
      ref: 'CS-5800',
      matches: [
        { ...match, extra: 'x' },
        { ...match, course_id: 'c-2' },
      ],
    }),
  ).toEqual([match, { ...match, course_id: 'c-2' }]);
  expect(parseResolved({ ref: 'dead-link', matches: [] })).toEqual([]);
  expect(
    parseResolved({ ref: 'x', matches: [{ ...match, primary_name: '' }] }),
  ).toEqual([{ ...match, primary_name: '' }]);
});

it.each([
  null,
  [],
  { ref: 'x' },
  { ref: 'x', matches: 'c-cs-5800' },
  { ref: 'x', matches: [null] },
  { ref: 'x', matches: [{ ...match, course_id: '' }] },
  { ref: 'x', matches: [{ ...match, course_id: ' ' }] },
  { ref: 'x', matches: [{ ...match, primary_code: 5800 }] },
  { ref: 'x', matches: [{ ...match, primary_name: null }] },
])('an answer that is not a list of courses is unreadable: %j', (value) => {
  expect(() => parseResolved(value)).toThrow(
    expect.objectContaining({ status: 502, errorType: 'invalid_response' }),
  );
});

it('asks /resolve/course with the ref as it is, and keeps the answer five minutes', async () => {
  const api = fakeApi(async () => json({ ref: 'CS-5800', matches: [match] }));
  const client: QueryClient = createQueryClient();
  expect(await client.fetchQuery(resolveQuery('CS-5800'))).toEqual([match]);
  expect(api.calls.map(asked)).toEqual(['GET /resolve/course?ref=CS-5800']);
  await client.fetchQuery(resolveQuery('CS-5800'));
  expect(api.calls).toHaveLength(1);
  expect(resolveQuery('CS-5800').staleTime).toBe(5 * 60_000);
});

it('waits 8 seconds for the lookup', async () => {
  await expectTimeout(
    () => createQueryClient().fetchQuery(resolveQuery('CS-5800')),
    'read',
  );
});

it('a refused ref is an ApiError, as the client makes it', async () => {
  fakeApi(async () =>
    json(
      {
        detail: 'ref: too long',
        error_type: 'invalid_input',
        status_code: 422,
      },
      422,
    ),
  );
  await expect(
    createQueryClient().fetchQuery(resolveQuery('x'.repeat(201))),
  ).rejects.toBeInstanceOf(ApiError);
});
