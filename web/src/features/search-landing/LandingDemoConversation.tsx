import { useEffect, useRef } from 'react';
import type { ChatSource } from '../../api/chat';
import { Button } from '../../components/Button';
import { SearchConversation } from '../search-answer/SearchConversation';
import { useConversation } from '../search-answer/useConversation';
import { showLanding } from '../../models/landing';
import { SearchLanding } from './SearchLanding';
import type { SearchLandingProps } from './SearchLanding';
import styles from './SearchLanding.module.css';

export type LandingDemoConversationProps = Omit<
  SearchLandingProps,
  'onAsk' | 'onRetry'
> & {
  sourceFor: (query: string) => ChatSource;
  onReset: () => void;
  onFollowUp: (text: string) => void;
};
export function LandingDemoConversation({
  sourceFor,
  onReset,
  onFollowUp,
  ...landing
}: LandingDemoConversationProps) {
  const { turns, busy, ask } = useConversation();
  const hasConversation = !showLanding(turns);
  const region = useRef<HTMLElement>(null);
  useEffect(() => {
    if (hasConversation) region.current?.focus({ preventScroll: true });
  }, [hasConversation]);
  return hasConversation ? (
    <section
      ref={region}
      tabIndex={-1}
      aria-label="搜索演示对话"
      className={styles.conversation}
    >
      <SearchConversation
        turns={turns}
        busy={busy}
        feedbackEnabled={false}
        onViewCourse={landing.onViewCourse}
        onFollowUp={onFollowUp}
        onFeedback={() =>
          Promise.reject(Error('Synthetic sample feedback is disabled'))
        }
      />
      <Button onClick={onReset}>回到落地页</Button>
    </section>
  ) : (
    <SearchLanding
      {...landing}
      onRetry={onReset}
      onAsk={(query) =>
        ask({ question: query, allowSave: false, source: sourceFor(query) })
      }
    />
  );
}
