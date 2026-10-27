import { expect, it } from 'vitest';
import { sendFeedback } from './feedback';
import { fakeApi, json } from '../test/fakeApi';
import { expectTimeout } from '../test/timeouts';

const vote = {
  answer_id: 'a'.repeat(32),
  answer_sha256: 'b'.repeat(64),
  feedback_token: 'c'.repeat(43),
  rating: 'up' as const,
};

it('posts exactly the receipt and the rating, as a write, and gives back the answer as it came', async () => {
  const api = fakeApi(async () =>
    json({ answer_id: vote.answer_id, rating: 'up' }),
  );
  const extra = { ...vote, question: 'private', turn: 3 };
  expect(await sendFeedback(extra)).toEqual({
    answer_id: vote.answer_id,
    rating: 'up',
  });
  expect(api.calls).toHaveLength(1);
  const [call] = api.calls;
  expect(call!.method).toBe('POST');
  expect(call!.path).toBe('/feedback');
  expect(call!.body).toEqual(vote);
  expect(new Headers(call!.init.headers).get('X-NEU-Compass')).toBe('1');
});

it('waits 8 seconds, the time R2b’s client gives feedback', async () => {
  await expectTimeout(() => sendFeedback(vote), 'read');
});

it('a refused vote is the client’s ApiError, never sent again by itself', async () => {
  const api = fakeApi(async () =>
    json(
      { detail: 'Receipt expired', error_type: 'not_found', status_code: 404 },
      404,
    ),
  );
  await expect(sendFeedback(vote)).rejects.toMatchObject({ status: 404 });
  expect(api.calls).toHaveLength(1);
});
