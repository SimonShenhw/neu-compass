import { useQuery } from '@tanstack/react-query';
import { ArrowUp, LockKeyhole } from 'lucide-react';
import { useCallback, useId, useLayoutEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { askNotices, privacyQuery } from '../api/privacy';
import { shownData } from '../api/queries';
import { IconButton } from '../components/IconButton';
import { useAccount, viewerScope } from './account';
import { MAX_QUESTION_CHARS, questionLength, useSearch } from './SearchContext';
import styles from './AskBar.module.css';

// Before every question (R0 3 ⑥). The words are the API's (GET /privacy, R2a); until it answers, the same sentence it
// gives today (api/privacy_text.py QUERY_LOG_NOTICE_BASE), so the notice is never missing.
export const QUERY_LOG_FALLBACK =
  '你的提问原文会记进不公开的查询日志。请不要输入个人信息或密码之类的秘密。';
// Streamlit's CAPTURE_OFF_NOTICE and its opt-in's label (app/answer_feedback_view.py). Once ticked, the answers after
// it are saved until it is unticked or the person logs out, which is what the API's capture notice says.
export const CAPTURE_OFF = '回答内容不会保存（回答反馈功能目前关闭）。';
export const CAPTURE_LABEL = '允许保存本次会话之后的回答，用于回答反馈';
export const PLACEHOLDER =
  '问任何课程问题：CS 5800 / 适合入门的 ML 课 / algo …';
// The custom property base.css reads for the page's scroll-margin-bottom, and the conversation's last turn for its
// height.
export const ASK_BAR_HEIGHT = '--ask-bar-height';
// Out of the form, the opt-in and its notice, or the line that nothing is saved, are a landmark of their own by this
// name, found beside 提问 (recheck 1 of round 34). Not 回答反馈: each answer's votes are a region by that name (R3c).
export const CAPTURE_REGION = '保存回答';

export function AskBar({ onSend }: { onSend: (question: string) => void }) {
  const search = useSearch();
  // Like the page's own requests, asked once it is known who is looking: back from Google, nothing but the login goes
  // out (R2b).
  const ready = viewerScope(useAccount()) !== null;
  const notices = askNotices(
    shownData(useQuery({ ...privacyQuery, enabled: ready })),
  );
  const [text, setText] = useState('');
  const id = useId();
  // Held at the bottom of the window (AskBar.module.css): while it is on the page, the page keeps what is focused or
  // scrolled into view clear of it, by its height (base.css's scroll-margin-bottom; R6).
  const form = useRef<HTMLFormElement>(null);
  const measure = useCallback(() => {
    const element = form.current;
    if (element)
      document.documentElement.style.setProperty(
        ASK_BAR_HEIGHT,
        `${element.offsetHeight}px`,
      );
  }, []);
  // After every render, as the notices, the opt-in and the length warning change its height, and on every resize, as
  // a narrower window wraps its lines.
  useLayoutEffect(measure);
  useLayoutEffect(() => {
    const element = form.current;
    if (!element) return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => {
      observer.disconnect();
      document.documentElement.style.removeProperty(ASK_BAR_HEIGHT);
    };
  }, [measure]);
  const length = questionLength(text.trim());
  const tooLong = length > MAX_QUESTION_CHARS;
  // One question at a time: the next waits until this answer has ended (R3c's conversation takes one).
  const canSend = length > 0 && !tooLong && !search.busy;
  const field = useRef<HTMLTextAreaElement>(null);
  function send() {
    if (!canSend) return;
    onSend(text.trim());
    setText('');
    // Sent with the button, which the empty box disables: a browser takes focus from it to the body, after the search
    // page has looked where focus is. It stays in the ask box, in the question's field, as after Enter (recheck 1 of
    // round 34).
    if (document.activeElement !== field.current)
      field.current?.focus({ preventScroll: true });
  }
  // The opt-in and its notice, or the sentence that no answer is kept: under the box, in the page, not held at the
  // bottom with it. Held there, with answer feedback on, they made the box about half a phone's window, and all of a
  // zoomed one (review A34). Still under the query log's sentence, which the notice names as above.
  const capture =
    search.feedback === true && notices?.capture ? (
      <>
        <label className={styles.optin}>
          <input
            type="checkbox"
            checked={search.allowSave}
            onChange={(event) => search.setAllowSave(event.target.checked)}
          />
          {CAPTURE_LABEL}
        </label>
        <p className={styles.note}>{notices.capture}</p>
      </>
    ) : search.feedback === false ? (
      <p className={styles.note}>{CAPTURE_OFF}</p>
    ) : null;
  return (
    <>
      <form
        ref={form}
        className={styles.askBar}
        aria-label="提问"
        onSubmit={(event) => {
          event.preventDefault();
          send();
        }}
      >
        <p className={styles.privacy} id={`${id}-privacy`}>
          <LockKeyhole aria-hidden="true" />
          <span>
            {notices?.queryLog ?? QUERY_LOG_FALLBACK}留多久、怎么删，见{' '}
            <Link to="/privacy">数据与隐私</Link>。
          </span>
        </p>
        <div className={styles.input}>
          <label className="visually-hidden" htmlFor={`${id}-query`}>
            课程问题
          </label>
          <textarea
            ref={field}
            id={`${id}-query`}
            rows={1}
            value={text}
            onChange={(event) => setText(event.target.value)}
            aria-describedby={
              tooLong ? `${id}-privacy ${id}-limit` : `${id}-privacy`
            }
            aria-invalid={tooLong}
            placeholder={PLACEHOLDER}
            onKeyDown={(event) => {
              if (
                event.key === 'Enter' &&
                !event.shiftKey &&
                !event.nativeEvent.isComposing
              ) {
                event.preventDefault();
                send();
              }
            }}
          />
          <IconButton
            type="submit"
            aria-label="发送问题"
            variant="primary"
            disabled={!canSend}
          >
            <ArrowUp aria-hidden="true" />
          </IconButton>
        </div>
        {tooLong && (
          <p id={`${id}-limit`} className={styles.limit}>
            {`问题最多 ${MAX_QUESTION_CHARS} 个字，现在是 ${length} 个字；改短一点再发。`}
          </p>
        )}
      </form>
      {capture && (
        <section className={styles.capture} aria-label={CAPTURE_REGION}>
          {capture}
        </section>
      )}
    </>
  );
}
