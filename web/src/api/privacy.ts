// R5c's contract. The API shapes come from the generated types (R2b); the rest is the page's own.
import { queryOptions } from '@tanstack/react-query';
import { answerStatus, apiGet, apiPath, apiPost, isJsonObject } from './client';
import { PUBLIC_FRESH_MS } from './queries';
import type { Schemas } from './types';

export type PrivacySection = Schemas['PrivacySectionOut'];
export type PrivacyBody = Schemas['PrivacyResponse'];
export type DeleteAccountResult = Schemas['DeleteAccountResponse'];
export type PrivacyState =
  | { status: 'loading' }
  | { status: 'error'; httpStatus: number | null }
  | { status: 'ready'; body: unknown };
export type DeleteOutcome =
  | { ok: true; result: DeleteAccountResult }
  | { ok: false; status: number | null };
export interface PrivacyPageProps {
  viewer: { kind: 'guest' } | { kind: 'member' };
  privacy: PrivacyState;
  onRetry: () => void;
  onDelete: () => Promise<DeleteOutcome>;
  onSignedOut: () => void;
}

// GET /privacy: the API's own words for its own settings (R2a), the body as it came for the page's check. The same
// for everyone; it stays fresh for five minutes, as the other public content does.
export const privacyQuery = queryOptions({
  queryKey: ['privacy'],
  queryFn: ({ signal }) =>
    apiGet(apiPath('/privacy'), { timeout: 'read', signal }),
  staleTime: PUBLIC_FRESH_MS,
});

// The two notices next to the ask box (R3e), from the same answer as the privacy page: the query log's always, the
// opt-in's while answer feedback is on (null otherwise). Null for an answer that does not carry them as text.
export function askNotices(
  value: unknown,
): { queryLog: string; capture: string | null } | null {
  if (
    !isJsonObject(value) ||
    typeof value.query_log_notice !== 'string' ||
    value.query_log_notice.trim() === '' ||
    !(
      value.capture_notice === null ||
      (typeof value.capture_notice === 'string' &&
        value.capture_notice.trim() !== '')
    )
  )
    return null;
  return { queryLog: value.query_log_notice, capture: value.capture_notice };
}

const COUNTS = [
  'published_experiences',
  'unlocks_of_those',
  'own_unlocks',
  'submissions',
  'credits',
  'planned_courses',
  'withdrawn_from_groups',
] as const satisfies readonly (keyof DeleteAccountResult)[];

// The deletion's 200: `deleted` and the seven counts of what went, each a whole number (only these keys are kept).
export function parseDeleteResult(value: unknown): DeleteAccountResult | null {
  if (!isJsonObject(value) || value.deleted !== true) return null;
  const counts = Object.fromEntries(COUNTS.map((name) => [name, value[name]]));
  return Object.values(counts).every(
    (count) =>
      typeof count === 'number' && Number.isSafeInteger(count) && count >= 0,
  )
    ? ({ deleted: true, ...counts } as DeleteAccountResult)
    : null;
}

// POST /auth/delete-account with exactly {"confirm": "delete"} (R5c), 15 seconds. A write, so it is never retried. A
// 200 this page cannot read still came from the API, and the account may well be gone: that is said as not known
// (502), as a lost answer is.
export async function deleteAccount(): Promise<DeleteOutcome> {
  let body: unknown;
  try {
    body = await apiPost(
      apiPath('/auth/delete-account'),
      { confirm: 'delete' },
      { timeout: 'write' },
    );
  } catch (error) {
    return { ok: false, status: answerStatus(error) };
  }
  const result = parseDeleteResult(body);
  return result ? { ok: true, result } : { ok: false, status: 502 };
}
