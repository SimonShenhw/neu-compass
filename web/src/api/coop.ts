// R5a's handwritten contract; R2 will replace it with generated API types.
export type Industry =
  | 'quant_fintech'
  | 'big_tech'
  | 'biotech_health'
  | 'startup'
  | 'consulting'
  | 'other';
export interface CoopRecord {
  coop_id: string;
  company: string;
  role: string;
  industry: Industry | null;
  coop_term: string | null;
  duration_months: number | null;
  related_courses: string[];
  interview_summary: string | null;
  technical_questions: string | null;
  salary_range_usd: string | null;
  visibility_level: 0 | 1 | 2;
}
export interface CoopUploadRequest {
  company: string;
  role: string;
  coop_term: string | null;
  industry: Industry | null;
  duration_months: number | null;
  related_courses: string[];
  interview_summary: string | null;
  technical_questions: string | null;
  salary_range_usd: string | null;
}
export interface CoopUploadResponse {
  coop_id: string;
  accepted: boolean;
  visibility_level: number;
  status: 'pending' | 'approved' | 'rejected' | 'published';
  duplicate: boolean;
  contribution_credited: boolean;
  contribution_count: number;
}
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
