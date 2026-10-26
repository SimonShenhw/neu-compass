import { expect, it } from 'vitest';
import { ApiError } from './client';
import { failureOf, loadOf } from './load';

const query = (overrides: Partial<Parameters<typeof loadOf>[0]>) => ({
  data: undefined,
  error: null,
  isError: false,
  isFetching: false,
  ...overrides,
});

it('what can be shown is ready, kept through a failure for a moment but not through a definite one', () => {
  expect(loadOf(query({ data: [1] }))).toEqual({
    status: 'ready',
    data: [1],
  });
  const busy = new ApiError(503, { errorType: 'service_busy' });
  expect(loadOf(query({ data: [1], error: busy, isError: true }))).toEqual({
    status: 'ready',
    data: [1],
  });
  const gone = new ApiError(404, { errorType: 'not_found' });
  expect(loadOf(query({ data: [1], error: gone, isError: true }))).toEqual({
    status: 'failed',
    failure: gone,
  });
});

it('nothing to show is loading, a new try after a failure included, and failed only once nothing is on its way', () => {
  expect(loadOf(query({}))).toEqual({ status: 'loading' });
  const busy = new ApiError(503, { errorType: 'service_busy' });
  expect(
    loadOf(query({ error: busy, isError: true, isFetching: true })),
  ).toEqual({ status: 'loading' });
  expect(loadOf(query({ error: busy, isError: true }))).toEqual({
    status: 'failed',
    failure: busy,
  });
});

it('a failure that is not an ApiError reads as an answer that did not come', () => {
  expect(failureOf(new TypeError('x'))).toMatchObject({
    status: 503,
    errorType: 'transport_error',
    retryAfter: null,
    invalidFields: [],
    reason: null,
  });
  const error = new ApiError(409, { reason: 'plan_stale' });
  expect(failureOf(error)).toBe(error);
});
