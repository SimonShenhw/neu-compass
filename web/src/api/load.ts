import { ApiError, isTransientError } from './client';
import { shownData } from './queries';

export type ApiFailure = Pick<
  ApiError,
  'status' | 'errorType' | 'retryAfter' | 'invalidFields' | 'reason'
>;
export type Load =
  | { status: 'loading' }
  | { status: 'ready'; data: unknown }
  | { status: 'failed'; failure: ApiFailure };

export function isTransient(failure: ApiFailure) {
  return isTransientError(new ApiError(failure.status, failure));
}

// What failed, as the components take it: an ApiError as it is; anything else (it never is) as an answer that did not
// come.
export function failureOf(error: unknown): ApiFailure {
  return error instanceof ApiError
    ? error
    : new ApiError(503, { errorType: 'transport_error' });
}

// A query's state as R3d's and R4a's components take it (R3e; R3d spec 2): what can be shown (shownData: the last
// success, kept through a failure that is only for a moment) is ready; a failure with nothing to show and no new try on
// its way is failed; anything else is loading, a new try after a failure included.
export function loadOf(query: {
  data: unknown;
  error: unknown;
  isError: boolean;
  isFetching: boolean;
}): Load {
  const data = shownData(query);
  if (data !== undefined) return { status: 'ready', data };
  if (query.isError && !query.isFetching)
    return { status: 'failed', failure: failureOf(query.error) };
  return { status: 'loading' };
}
