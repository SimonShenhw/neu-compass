// Handwritten R5c contract. R2 will replace this with generated API types.
export interface PrivacySection {
  heading: string;
  sentences: string[];
}
export interface PrivacyBody {
  intro: string;
  sections: PrivacySection[];
  delete_what: string;
  query_log_notice: string;
  capture_notice: string | null;
}
export interface DeleteAccountResult {
  deleted: true;
  published_experiences: number;
  unlocks_of_those: number;
  own_unlocks: number;
  submissions: number;
  credits: number;
  planned_courses: number;
  withdrawn_from_groups: number;
}
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
