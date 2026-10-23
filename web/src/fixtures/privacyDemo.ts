import type { DeleteOutcome, PrivacyState } from '../api/privacy';
import p90 from './privacy/privacy-90-days-feedback-contact.json';
import pOff from './privacy/privacy-no-cleanup-feedback-off.json';
import p30 from './privacy/privacy-30-days-feedback-no-contact.json';
import pContact from './privacy/privacy-no-cleanup-feedback-contact.json';
import ok from './privacy/delete-ok.json';
import okEmpty from './privacy/delete-ok-nothing-else.json';
import stale from './privacy/delete-401-cookie-not-valid.json';
import gone from './privacy/delete-401-account-gone.json';
import crossSite from './privacy/delete-403-cross-site.json';
import wrongWord from './privacy/delete-422-wrong-word.json';

export const privacyViewerOptions = ['guest', 'member'] as const;
export const privacyOptions = [
  '90-days',
  'no-cleanup-off',
  '30-days',
  'no-cleanup-contact',
  'loading',
  'error',
  'network',
  'unrecognised',
] as const;
export const deleteOptions = [
  'ok',
  'ok-nothing',
  '401-stale',
  '401-gone',
  '403',
  '422',
  '503',
  'network',
] as const;
export type PrivacyDemoChoice = (typeof privacyOptions)[number];
export type DeleteDemoChoice = (typeof deleteOptions)[number];
export function readChoice<T extends string>(
  value: string | null,
  options: readonly T[],
): T {
  return options.find((option) => option === value) ?? options[0]!;
}
const policy = {
  '90-days': p90,
  'no-cleanup-off': pOff,
  '30-days': p30,
  'no-cleanup-contact': pContact,
};
export function demoPrivacy(choice: PrivacyDemoChoice): PrivacyState {
  if (choice === 'loading') return { status: 'loading' };
  if (choice === 'error' || choice === 'network')
    return { status: 'error', httpStatus: choice === 'network' ? null : 503 };
  if (choice === 'unrecognised')
    return { status: 'ready', body: { intro: 'x' } };
  return { status: 'ready', body: policy[choice].body };
}
export function demoDeletion(choice: DeleteDemoChoice): DeleteOutcome {
  if (choice === 'network') throw Error('Synthetic network failure');
  if (choice === 'ok' || choice === 'ok-nothing')
    return {
      ok: true,
      result: { ...(choice === 'ok' ? ok : okEmpty).body, deleted: true },
    };
  const errors = {
    '401-stale': stale,
    '401-gone': gone,
    '403': crossSite,
    '422': wrongWord,
  };
  return { ok: false, status: choice === '503' ? 503 : errors[choice].status };
}
