import type { FeedbackReceipt, FeedbackVote } from '../api/chat';
import { fullMatch, object, string } from './searchGuard';

export function parseReceipt(v: unknown): FeedbackReceipt | null {
  if (
    !object(v) ||
    Object.keys(v).length !== 3 ||
    Object.keys(v).sort().join(',') !==
      'answer_id,answer_sha256,feedback_token' ||
    !string(v.answer_id) ||
    !fullMatch(/[a-f0-9]{32}/, v.answer_id) ||
    !string(v.answer_sha256) ||
    !fullMatch(/[a-f0-9]{64}/, v.answer_sha256) ||
    !string(v.feedback_token) ||
    !fullMatch(/[A-Za-z0-9_-]{43}/, v.feedback_token)
  )
    return null;
  return {
    answer_id: v.answer_id,
    answer_sha256: v.answer_sha256,
    feedback_token: v.feedback_token,
  };
}
export async function verifiedReceipt(
  text: string,
  raw: unknown,
): Promise<FeedbackReceipt | null> {
  const receipt = parseReceipt(raw);
  if (!receipt || text.trim() === '') return null;
  try {
    const digest = await crypto.subtle.digest(
      'SHA-256',
      new TextEncoder().encode(text),
    );
    const hex = [...new Uint8Array(digest)]
      .map((n) => n.toString(16).padStart(2, '0'))
      .join('');
    return hex === receipt.answer_sha256 ? receipt : null;
  } catch {
    return null;
  }
}
export function feedbackResponseMatches(v: unknown, vote: FeedbackVote) {
  return (
    object(v) &&
    Object.keys(v).length === 2 &&
    Object.keys(v).sort().join(',') === 'answer_id,rating' &&
    v.answer_id === vote.answer_id &&
    v.rating === vote.rating
  );
}
