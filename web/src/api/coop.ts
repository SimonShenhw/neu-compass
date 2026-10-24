// R5a's contract. The API shapes come from the generated types (R2b); the rest is the page's own. The list and the
// upload go through here (R5d).
import { queryOptions } from '@tanstack/react-query';
import {
  ApiError,
  apiGet,
  apiPath,
  apiPost,
  isJsonObject,
  unreadableAnswer,
} from './client';
import type { Schemas } from './types';

export type Industry = Schemas['Industry'];
// A Co-op row as the page shows it: the API's CoopOut, narrowed to what the API puts there (its schema says only
// "a string" and "an integer"). parseCoopList checks each row against this before the page gets it.
export type CoopRecord = Omit<
  Schemas['CoopOut'],
  'industry' | 'visibility_level'
> & {
  industry: Industry | null;
  visibility_level: 0 | 1 | 2;
};
// The form always sends every field, so none is optional here.
export type CoopUploadRequest = Required<Schemas['CoopUploadRequest']>;
export type CoopUploadResponse = Schemas['CoopUploadResponse'];
export type CoopViewer =
  { kind: 'guest' } | { kind: 'member'; contributionCount: number };
export type CoopListState =
  | { status: 'loading' }
  | { status: 'error' }
  | { status: 'ready'; records: CoopRecord[] };
// A failed upload as R2b's ApiError has it: the status, the API's error_type (null when the answer was not the API's,
// such as a proxy's page) and for a 422 the fields it refused. Never the API's detail text (R2b, R5d).
export type SubmitFailure = Pick<
  ApiError,
  'status' | 'errorType' | 'invalidFields'
>;
export type SubmitOutcome =
  { ok: true; result: CoopUploadResponse } | ({ ok: false } & SubmitFailure);
export interface CoopPageProps {
  viewer: CoopViewer;
  list: CoopListState;
  onRetryList: () => void;
  onSubmit: (request: CoopUploadRequest) => Promise<SubmitOutcome>;
  onLogin: () => void;
}

// Every industry the API knows; a new one in the generated type stops this compiling until it is added.
const INDUSTRIES: Readonly<Record<Industry, true>> = {
  quant_fintech: true,
  big_tech: true,
  biotech_health: true,
  startup: true,
  consulting: true,
  other: true,
};
const isText = (value: unknown): value is string => typeof value === 'string';
const isIndustry = (value: unknown): value is Industry =>
  isText(value) && Object.hasOwn(INDUSTRIES, value);
// A field the API may leave out is read as null, as R2b reads a missing display name.
const textOrNull = (value: unknown): string | null | undefined =>
  value === undefined || value === null
    ? null
    : typeof value === 'string'
      ? value
      : undefined;

function coopRecord(value: unknown): CoopRecord | null {
  if (!isJsonObject(value)) return null;
  const { coop_id, company, role, related_courses, visibility_level } = value;
  const industry = value.industry ?? null;
  const duration = value.duration_months ?? null;
  const term = textOrNull(value.coop_term);
  const interview = textOrNull(value.interview_summary);
  const questions = textOrNull(value.technical_questions);
  const salary = textOrNull(value.salary_range_usd);
  if (
    !isText(coop_id) ||
    coop_id === '' ||
    !isText(company) ||
    !isText(role) ||
    !(industry === null || isIndustry(industry)) ||
    !(
      duration === null ||
      (typeof duration === 'number' &&
        Number.isInteger(duration) &&
        duration >= 1 &&
        duration <= 8)
    ) ||
    !Array.isArray(related_courses) ||
    !related_courses.every(isText) ||
    term === undefined ||
    interview === undefined ||
    questions === undefined ||
    salary === undefined ||
    !(
      visibility_level === 0 ||
      visibility_level === 1 ||
      visibility_level === 2
    )
  )
    return null;
  return {
    coop_id,
    company,
    role,
    industry,
    coop_term: term,
    duration_months: duration,
    related_courses: [...related_courses],
    interview_summary: interview,
    technical_questions: questions,
    salary_range_usd: salary,
    visibility_level,
  };
}

// GET /coop's answer: a list of rows, each as CoopRecord says. One row the page cannot read makes the whole answer
// unreadable, as a malformed identity is (R2b): the page shows no half list.
export function parseCoopList(value: unknown): CoopRecord[] {
  if (!Array.isArray(value)) throw unreadableAnswer();
  return value.map((item) => {
    const record = coopRecord(item);
    if (!record) throw unreadableAnswer();
    return record;
  });
}

// The Co-op list as this viewer may see it: the API leaves out what the viewer's level does not unlock, so the key
// carries who is asking (account.ts viewerScope; R0 14.9) and the whole group goes at login and logout (VIEWER_KEY).
// Streamlit's Co-op page asks every time it is drawn, so nothing is fresh for long here: every visit asks again.
export function coopListQuery(scope: string) {
  return queryOptions({
    queryKey: ['viewer', scope, 'coop'],
    queryFn: async ({ signal }) =>
      parseCoopList(
        await apiGet(apiPath('/coop'), { timeout: 'slow', signal }),
      ),
    staleTime: 0,
  });
}

const STATUSES = new Set<unknown>([
  'pending',
  'approved',
  'rejected',
  'published',
]);

export function parseUploadResponse(value: unknown): CoopUploadResponse {
  if (isJsonObject(value)) {
    const {
      coop_id,
      accepted,
      visibility_level,
      status,
      duplicate,
      contribution_credited,
      contribution_count,
    } = value;
    if (
      isText(coop_id) &&
      coop_id !== '' &&
      typeof accepted === 'boolean' &&
      typeof visibility_level === 'number' &&
      Number.isInteger(visibility_level) &&
      STATUSES.has(status) &&
      typeof duplicate === 'boolean' &&
      typeof contribution_credited === 'boolean' &&
      typeof contribution_count === 'number' &&
      Number.isInteger(contribution_count) &&
      contribution_count >= 0
    )
      return {
        coop_id,
        accepted,
        visibility_level,
        status: status as CoopUploadResponse['status'],
        duplicate,
        contribution_credited,
        contribution_count,
      };
  }
  throw unreadableAnswer();
}

// POST /coop. A write: never retried, here or anywhere (a timed-out upload may have been stored; sending it again
// gets the API's "duplicate" answer).
export async function uploadCoop(
  request: CoopUploadRequest,
): Promise<CoopUploadResponse> {
  return parseUploadResponse(
    await apiPost(apiPath('/coop'), request, { timeout: 'slow' }),
  );
}

// What the page is told about a failed upload. Anything but an ApiError is not the API's answer: the form says the
// upload could not be sent, as for a lost connection.
export function submitFailure(error: unknown): { ok: false } & SubmitFailure {
  if (error instanceof ApiError)
    return {
      ok: false,
      status: error.status,
      errorType: error.errorType,
      invalidFields: error.invalidFields,
    };
  return {
    ok: false,
    status: 503,
    errorType: 'transport_error',
    invalidFields: [],
  };
}
