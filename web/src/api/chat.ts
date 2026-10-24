// R3c consumption contract. R3 will replace these with R2b's stream/client types.
export type ChatEvent =
  | { type: 'meta'; meta: Readonly<Record<string, unknown>> }
  | { type: 'token'; text: string }
  | { type: 'error'; errorType: string; message: string }
  | { type: 'done'; feedback: unknown };
export interface ChatFailure {
  status: number;
  errorType: string | null;
  retryAfter: number | null;
  invalidFields: readonly string[];
  reason: string | null;
}
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
