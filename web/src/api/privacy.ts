// R5c's contract. The API shapes come from the generated types (R2b); the rest is the page's own.
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
