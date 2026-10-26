import { expect, it } from 'vitest';
import { asked, fakeApi, json } from '../test/fakeApi';
import { expectTimeout } from '../test/timeouts';
import { curriculumQuery, programListQuery } from './programs';
import { PUBLIC_FRESH_MS, createQueryClient } from './queries';

it('the program list is GET /programs, the same for everyone and fresh for five minutes, waiting 8 seconds', async () => {
  expect(programListQuery.queryKey).toEqual(['programs']);
  expect(programListQuery.staleTime).toBe(PUBLIC_FRESH_MS);
  const rows = [{ program_id: 'cs-ms' }];
  const api = fakeApi(() => json(rows));
  expect(await createQueryClient().fetchQuery(programListQuery)).toEqual(rows);
  expect(api.calls.map(asked)).toEqual(['GET /programs']);
  await expectTimeout(
    () => createQueryClient().fetchQuery(programListQuery),
    'read',
  );
});

it('a program is GET /programs/{id}, its ID encoded, under the list’s key and as fresh, waiting 8 seconds', async () => {
  const query = curriculumQuery('cs ms/1');
  expect(query.queryKey).toEqual(['programs', 'cs ms/1']);
  expect(query.staleTime).toBe(PUBLIC_FRESH_MS);
  const body = { program_id: 'cs ms/1' };
  const api = fakeApi(() => json(body));
  expect(await createQueryClient().fetchQuery(query)).toEqual(body);
  expect(api.calls.map(asked)).toEqual(['GET /programs/cs%20ms%2F1']);
  await expectTimeout(
    () => createQueryClient().fetchQuery(curriculumQuery('cs-ms')),
    'read',
  );
});
