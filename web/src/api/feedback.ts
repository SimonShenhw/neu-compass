// POST /feedback (R3e): one latest vote on an answer, with the receipt its done event carried (R0 3). Sent only on a
// click and never again by itself; R3c's AnswerFeedback checks the answer against the vote. The body is exactly the
// receipt and the rating, nothing else the page holds.
import type { FeedbackVote } from './chat';
import { apiPath, apiPost } from './client';

export function sendFeedback(vote: FeedbackVote): Promise<unknown> {
  return apiPost(
    apiPath('/feedback'),
    {
      answer_id: vote.answer_id,
      answer_sha256: vote.answer_sha256,
      feedback_token: vote.feedback_token,
      rating: vote.rating,
    },
    { timeout: 'read' },
  );
}
