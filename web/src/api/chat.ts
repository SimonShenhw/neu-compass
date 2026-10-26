// R3c's consumption contract. Since R3e the stream's events and a refusal's failure are R2b's own (chatStream.ts,
// client.ts), so R3c's components read exactly what streamChat gives; the rest is the page's view of meta and of the
// feedback receipt.
import type { ApiFailure } from './load';
import type { ChatEvent } from './chatStream';

export type { ChatEvent };
export type ChatFailure = ApiFailure;
export interface ChatResult {
  course_id: string;
  primary_code: string;
  primary_name: string;
  score: number;
  answer_evidence?: unknown;
}
export interface ChatMeta {
  matched_via: string;
  results: ChatResult[];
  notices?: unknown;
  plan_context?: unknown;
}
export interface FeedbackReceipt {
  answer_id: string;
  answer_sha256: string;
  feedback_token: string;
}
export type ChatSource = (signal: AbortSignal) => AsyncIterable<ChatEvent>;
export interface AskOptions {
  question: string;
  allowSave: boolean;
  source: ChatSource;
}
export type FeedbackVote = FeedbackReceipt & { rating: 'up' | 'down' };
