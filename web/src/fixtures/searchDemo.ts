import type {
  ChatEvent,
  ChatFailure,
  ChatSource,
  FeedbackVote,
} from '../api/chat';

export interface SearchFixture {
  case: string;
  notes: string;
  request: { body: { query: string; allow_feedback_capture?: boolean } };
  events: ChatEvent[];
  failure: ChatFailure | null;
  proposed_reason?: string;
}
const fixtures = import.meta.glob<SearchFixture>(
  ['./search/*.json', '!./search/feedback-responses.json'],
  { eager: true, import: 'default' },
);
export const searchFixtures = Object.values(fixtures);
export const searchCases = [
  ...searchFixtures.map((f) => f.case),
  'conversation-followup',
  'conversation-four-turns',
];
export function searchFixture(name: string) {
  const fixture = searchFixtures.find((f) => f.case === name);
  if (!fixture) throw new Error('Unknown synthetic search case');
  return fixture;
}
export function searchSequence(name: string): string[] {
  if (name === 'conversation-followup')
    return ['alias-cs-6140', 'context-followup'];
  if (name === 'conversation-four-turns')
    return [
      'hybrid-neural-network',
      'refused-422-too-long',
      'model-error',
      'alias-cs-6140',
    ];
  return [name];
}
export type SearchSpeed = 'normal' | 'slow' | 'instant';
export type VoteOutcome = 'saved' | '404' | '503' | 'mismatch';
export function demoOptions(params: URLSearchParams) {
  const choose = <T extends string>(
    name: string,
    values: readonly T[],
    fallback: T,
  ) => values.find((v) => v === params.get(name)) ?? fallback;
  return {
    caseName: choose('case', searchCases, 'alias-cs-6140'),
    feedback: choose('feedback', ['on', 'off'], 'off'),
    reason: choose('reason', ['on', 'off'], 'on'),
    vote: choose<VoteOutcome>(
      'vote',
      ['saved', '404', '503', 'mismatch'],
      'saved',
    ),
    speed: choose<SearchSpeed>(
      'speed',
      ['normal', 'slow', 'instant'],
      'normal',
    ),
  };
}
function wait(ms: number, signal: AbortSignal): Promise<void> {
  if (signal.aborted) return Promise.reject(signal.reason);
  if (ms === 0) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const abort = () => {
      clearTimeout(timer);
      signal.removeEventListener('abort', abort);
      reject(signal.reason);
    };
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', abort);
      resolve();
    }, ms);
    signal.addEventListener('abort', abort, { once: true });
  });
}
export function demoSource(
  fixture: SearchFixture,
  speed: SearchSpeed,
  withReason: boolean,
): ChatSource {
  const multiplier = speed === 'instant' ? 0 : speed === 'slow' ? 4 : 1;
  return async function* (signal) {
    await wait(400 * multiplier, signal);
    if (fixture.failure)
      throw {
        ...fixture.failure,
        reason: withReason
          ? (fixture.proposed_reason ?? fixture.failure.reason)
          : fixture.failure.reason,
      };
    for (let i = 0; i < fixture.events.length; i++) {
      if (i > 0) await wait(150 * multiplier, signal);
      if (signal.aborted) throw signal.reason;
      const event = fixture.events[i]!;
      yield event;
      if (event.type === 'error' || event.type === 'done') return;
    }
  };
}
export async function demoFeedback(
  vote: FeedbackVote,
  outcome: VoteOutcome,
): Promise<unknown> {
  if (outcome === '404' || outcome === '503')
    throw {
      status: Number(outcome),
      errorType: null,
      retryAfter: null,
      invalidFields: [],
      reason: null,
    };
  return {
    answer_id: vote.answer_id,
    rating:
      outcome === 'saved' ? vote.rating : vote.rating === 'up' ? 'down' : 'up',
  };
}
