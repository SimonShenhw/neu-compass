import { expect, it } from 'vitest';
import cs5800 from '../fixtures/compare/course-cs-5800.json';
import { fakeApi, json } from '../test/fakeApi';
import { expectTimeout } from '../test/timeouts';
import { courseQuery } from './course';
import { createQueryClient } from './queries';

it('a course is GET /course/{course_id} under its own key, the body as it came, waiting 30 seconds', async () => {
  expect(courseQuery('c-cs-5800').queryKey).toEqual(['course', 'c-cs-5800']);
  const api = fakeApi(() => json(cs5800.body));
  expect(
    await createQueryClient().fetchQuery(courseQuery('c-cs-5800')),
  ).toEqual(cs5800.body);
  expect(api.calls.map((call) => `${call.method} ${call.path}`)).toEqual([
    'GET /course/c-cs-5800',
  ]);
  await expectTimeout(
    () => createQueryClient().fetchQuery(courseQuery('c-cs-5800')),
    'slow',
  );
});

it('any JSON body is handed on for the page to check, even one that is not a course', async () => {
  fakeApi(() => json(null));
  expect(
    await createQueryClient().fetchQuery(courseQuery('c-cs-5800')),
  ).toBeNull();
});
