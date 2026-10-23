// R5a's contract. The API shapes come from the generated types (R2b); the rest is the page's own.
import type { Schemas } from './types';

export type Industry = Schemas['Industry'];
// A Co-op row as the page shows it: the API's CoopOut, narrowed to what the API puts there (its schema says only
// "a string" and "an integer"). R5d checks each row against this before the page gets it.
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
// The API's error body (api/exceptions.py); OpenAPI does not describe it.
export interface ApiErrorBody {
  detail: string;
  error_type: string;
  status_code: number;
}
export type CoopViewer =
  { kind: 'guest' } | { kind: 'member'; contributionCount: number };
export type CoopListState =
  | { status: 'loading' }
  | { status: 'error' }
  | { status: 'ready'; records: CoopRecord[] };
export type SubmitOutcome =
  | { ok: true; result: CoopUploadResponse }
  | { ok: false; status: number; body: ApiErrorBody | null };
export interface CoopPageProps {
  viewer: CoopViewer;
  list: CoopListState;
  onRetryList: () => void;
  onSubmit: (request: CoopUploadRequest) => Promise<SubmitOutcome>;
  onLogin: () => void;
}
