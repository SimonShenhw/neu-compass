import { expect, it } from 'vitest';
import refused from '../fixtures/draft/draft-409-unavailable.json';
import added from '../fixtures/draft/draft-standard-add.json';
import { fakeApi, json } from '../test/fakeApi';
import { expectTimeout } from '../test/timeouts';
import { checkDraft } from './draft';

const STANDARD = 'cs-ms-boston-2026-2027-standard';
const body = {
  plan_content_sha256: added.request.body.plan_content_sha256,
  course_ids: [],
  input: 'CS 5010, CS 5800',
};

it('posts exactly the version, the course IDs and the text to the plan’s draft check, as a write', async () => {
  const api = fakeApi(async () => json(added.body));
  expect(await checkDraft('cs-ms', STANDARD, body)).toEqual(added.body);
  expect(api.calls).toHaveLength(1);
  const [call] = api.calls;
  expect(call!.method).toBe('POST');
  expect(call!.path).toBe(added.request.path);
  expect(call!.body).toEqual(added.request.body);
  expect(new Headers(call!.init.headers).get('X-NEU-Compass')).toBe('1');
});

it('waits 15 seconds, the write timeout', async () => {
  await expectTimeout(() => checkDraft('cs-ms', STANDARD, body), 'write');
});

it('a refusal is the client’s ApiError with its reason, never sent again by itself', async () => {
  const api = fakeApi(async () => json(refused.body, 409));
  await expect(checkDraft('cs-ms', STANDARD, body)).rejects.toMatchObject({
    status: 409,
    reason: 'unavailable',
  });
  expect(api.calls).toHaveLength(1);
});

it('a check its caller stops is stopped on the way', async () => {
  const api = fakeApi(() => new Promise<Response>(() => {}));
  const stop = new AbortController();
  void checkDraft('cs-ms', STANDARD, body, stop.signal).catch(() => {});
  stop.abort();
  expect(api.calls[0]!.init.signal?.aborted).toBe(true);
});
