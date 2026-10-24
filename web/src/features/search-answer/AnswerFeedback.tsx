import { useEffect, useRef, useState } from 'react';
import type { FeedbackReceipt, FeedbackVote } from '../../api/chat';
import type { Turn } from '../../models/chatTurn';
import {
  feedbackResponseMatches,
  parseReceipt,
  verifiedReceipt,
} from '../../models/answerFeedback';
import { isChatFailure } from '../../models/chatFailure';
import { Button } from '../../components/Button';
import { SearchText } from './SearchParts';
import styles from './SearchConversation.module.css';

export interface FeedbackProps {
  turn: Turn;
  feedbackEnabled: boolean;
  onFeedback: (vote: FeedbackVote) => Promise<unknown>;
}
export function AnswerFeedback({
  turn,
  feedbackEnabled,
  onFeedback,
}: FeedbackProps) {
  const [verified, setVerified] = useState<{
    text: string;
    receipt: FeedbackReceipt;
  } | null>(null);
  const eligible = feedbackEnabled && turn.allowSave && turn.status === 'done';
  const candidate = parseReceipt(turn.receipt);
  const id = candidate?.answer_id,
    hash = candidate?.answer_sha256,
    token = candidate?.feedback_token;
  useEffect(() => {
    let live = true;
    if (eligible && id && hash && token)
      void verifiedReceipt(turn.text, {
        answer_id: id,
        answer_sha256: hash,
        feedback_token: token,
      }).then((receipt) => {
        if (live && receipt) setVerified({ text: turn.text, receipt });
      });
    return () => {
      live = false;
    };
  }, [eligible, id, hash, token, turn.text]);
  if (
    !eligible ||
    !verified ||
    verified.receipt.answer_id !== id ||
    verified.receipt.answer_sha256 !== hash ||
    verified.receipt.feedback_token !== token ||
    verified.text !== turn.text
  )
    return null;
  return <FeedbackButtons receipt={verified.receipt} onFeedback={onFeedback} />;
}
function FeedbackButtons({
  receipt,
  onFeedback,
}: {
  receipt: FeedbackReceipt;
  onFeedback: FeedbackProps['onFeedback'];
}) {
  const [rating, setRating] = useState<'up' | 'down' | null>(null);
  const [pending, setPending] = useState(false);
  const [status, setStatus] = useState('');
  const locked = useRef(false),
    mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  async function vote(next: 'up' | 'down') {
    if (locked.current || next === rating) return;
    locked.current = true;
    setPending(true);
    const request: FeedbackVote = {
      answer_id: receipt.answer_id,
      answer_sha256: receipt.answer_sha256,
      feedback_token: receipt.feedback_token,
      rating: next,
    };
    try {
      const response = await onFeedback(request);
      if (!mounted.current) return;
      if (feedbackResponseMatches(response, request)) {
        setRating(next);
        setStatus('反馈已保存，仅记录此回答的一条最新评价。');
      } else setStatus('反馈响应校验失败；未标记为成功。');
    } catch (error) {
      if (!mounted.current) return;
      setStatus(
        isChatFailure(error) && error.status === 404
          ? '反馈凭证已过期或不可用；未保存本次评价。'
          : '反馈暂时无法保存；未标记为成功，可稍后重试。',
      );
    } finally {
      locked.current = false;
      if (mounted.current) setPending(false);
    }
  }
  return (
    <section
      className={styles.feedback}
      aria-label="回答反馈"
      aria-busy={pending}
    >
      <SearchText>
        只评价这条回答；不是选课或毕业资格确认。反馈关联此回答及原查询，不收额外文本。
      </SearchText>
      <div className={styles.actions}>
        {(['up', 'down'] as const).map((value) => (
          <Button
            key={value}
            data-kind="button"
            aria-pressed={rating === value}
            disabled={pending || rating === value}
            onClick={() => {
              void vote(value);
            }}
          >
            {value === 'up' ? '有帮助' : '没帮助'}
          </Button>
        ))}
      </div>
      {status && (
        <p data-kind="feedback_status" role="status" className={styles.note}>
          {status}
        </p>
      )}
      {rating !== null && (
        <SearchText>已记录评价，可点击另一项修改。</SearchText>
      )}
    </section>
  );
}
