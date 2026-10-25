import { ApiError, isTransientError } from './client';

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
