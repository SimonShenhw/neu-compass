import type { FeedbackVote } from '../../api/chat';
import type { Turn } from '../../models/chatTurn';
import { isRunning } from '../../models/chatTurn';
import { BAD_RESULTS } from '../../models/chatMeta';
import { chatFailureMessage, UNKNOWN_FAILURE } from '../../models/chatFailure';
import { Button } from '../../components/Button';
import { AnswerText } from './AnswerText';
import { AnswerFeedback } from './AnswerFeedback';
import { PlanPosition, RelatedCourses, SearchText } from './SearchParts';
import styles from './SearchConversation.module.css';

export interface SearchConversationProps {
  turns: readonly Turn[];
  busy: boolean;
  feedbackEnabled: boolean;
  onViewCourse: (courseId: string) => void;
  onFollowUp: (question: string) => void;
  onFeedback: (vote: FeedbackVote) => Promise<unknown>;
}
export const SINGLE_FOLLOWUPS = [
  '这门课讲什么内容？',
  '这门课作业量大吗？',
  '先修要求是什么？',
];
export const MULTI_FOLLOWUPS = [
  '这几门课怎么选？',
  '哪门最适合零基础？',
  '第一门的先修要求？',
];
export const SCHEDULE_NOTICE =
  '该项目已有版本化培养方案规则，但没有经过核验的学期安排；以上只是检索到的相关课程，不是官方的第一学期/基础课方案。具体规则请到「培养方案」页查看。';
export function SearchConversation({
  turns,
  busy,
  feedbackEnabled,
  onViewCourse,
  onFollowUp,
  onFeedback,
}: SearchConversationProps) {
  const last = turns.at(-1);
  const announcement = busy
    ? '正在回答…'
    : last?.status === 'done'
      ? '回答完成。'
      : last?.status === 'stopped'
        ? '回答没有完成。'
        : last?.status === 'failed'
          ? chatFailureMessage(last.failure ?? UNKNOWN_FAILURE)
          : '';
  return (
    <div
      className={styles.conversation}
      aria-label="搜索对话"
      data-search-conversation
    >
      <p className={styles.srOnly} role="status" aria-label="回答状态">
        {announcement}
      </p>
      {turns.map((turn, index) => (
        <section
          key={turn.id}
          className={styles.turn}
          aria-label={`第 ${index + 1} 轮问答`}
        >
          <p data-kind="question" className={styles.question}>
            {turn.question}
          </p>
          {turn.status === 'failed' ? (
            <SearchText kind="failure">
              {chatFailureMessage(turn.failure ?? UNKNOWN_FAILURE)}
            </SearchText>
          ) : (
            <article
              aria-label={`第 ${index + 1} 轮回答`}
              aria-busy={isRunning(turn)}
              className={styles.response}
            >
              {turn.text !== '' && <AnswerText text={turn.text} />}
              {turn.status === 'waiting' && (
                <p className={styles.note}>正在查找相关的课…</p>
              )}
              {turn.status === 'answering' && turn.text === '' && (
                <p className={styles.note}>正在生成回答…</p>
              )}
              {turn.error && (
                <SearchText kind="stream_error">
                  {turn.error.message}
                </SearchText>
              )}
              {turn.meta?.kind === 'ok' && (
                <>
                  {Array.isArray(turn.meta.notices) &&
                    turn.meta.notices.map((code, n) =>
                      code === 'program_schedule_unverified' ? (
                        <SearchText kind="notice" key={n}>
                          {SCHEDULE_NOTICE}
                        </SearchText>
                      ) : null,
                    )}
                  <PlanPosition meta={turn.meta} />
                  <RelatedCourses
                    meta={turn.meta}
                    onViewCourse={onViewCourse}
                  />
                </>
              )}
              {turn.meta?.kind === 'invalid' && (
                <SearchText kind="failure">{BAD_RESULTS}</SearchText>
              )}
              <AnswerFeedback
                turn={turn}
                feedbackEnabled={feedbackEnabled}
                onFeedback={onFeedback}
              />
              {index === turns.length - 1 &&
                (turn.status === 'done' || turn.status === 'stopped') &&
                turn.meta?.kind === 'ok' &&
                turn.meta.results.length > 0 &&
                !['rejected', 'empty'].includes(turn.meta.matched_via) && (
                  <div
                    className={styles.actions}
                    role="group"
                    aria-label="接着问"
                  >
                    {(turn.meta.results.length === 1
                      ? SINGLE_FOLLOWUPS
                      : MULTI_FOLLOWUPS
                    ).map((text) => (
                      <Button
                        key={text}
                        size="sm"
                        data-kind="followup"
                        disabled={busy}
                        onClick={() => onFollowUp(text)}
                      >
                        {text}
                      </Button>
                    ))}
                  </div>
                )}
            </article>
          )}
        </section>
      ))}
    </div>
  );
}
