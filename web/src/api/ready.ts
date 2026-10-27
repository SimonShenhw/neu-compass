import { queryOptions } from '@tanstack/react-query';
import { apiGet, apiPath, isJsonObject } from './client';
import { PUBLIC_FRESH_MS } from './queries';

// GET /ready, for the top bar's course count (R3e; R0 1 and 0.5): public, 5 seconds, fresh for five minutes, as
// Streamlit's _ready_info. The one read that goes again by itself: a failure (the API's 503 while it warms up) is
// tried again 30 seconds later, as app/view_cache.py's FAILURE_TTL_SECONDS has the next rerun do, so the count comes
// back without a refresh. It has no failure line of its own; the bar names the catalog without a number instead.
export const READY_RETRY_MS = 30_000;
export const readyQuery = queryOptions({
  queryKey: ['ready'],
  queryFn: ({ signal }) =>
    apiGet(apiPath('/ready'), { timeout: 'quick', signal }),
  staleTime: PUBLIC_FRESH_MS,
  refetchInterval: ({ state }) =>
    state.status === 'error' ? READY_RETRY_MS : false,
});

// The count the bar shows: courses_indexed while it is a whole number above 0, as hero_html shows it; otherwise
// (nothing yet, warming up, an answer it cannot read) null.
export function coursesIndexed(body: unknown): number | null {
  if (!isJsonObject(body)) return null;
  const count = body.courses_indexed;
  return typeof count === 'number' && Number.isSafeInteger(count) && count > 0
    ? count
    : null;
}
