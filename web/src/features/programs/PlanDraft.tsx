import { Info, TriangleAlert } from 'lucide-react';
import { Fragment, useId, useRef, useState } from 'react';
import type { RefObject } from 'react';
import type { DraftAnswer } from '../../api/draft';
import type { ApiFailure } from '../../api/load';
import type { ProgramPlanDoc } from '../../api/programs';
import { Button } from '../../components/Button';
import {
  canRetryDraft,
  creditsText,
  DRAFT_INPUT_MAX,
  draftFailureMessage,
  draftTreeLines,
  MAX_DRAFT_COURSES,
  parseDraftAnswer,
} from '../../models/planDraft';
import styles from './PlanDraft.module.css';

// R4b: the selected plan's course draft (R0 7, R4B_DRAFT_SPEC.md). Controlled: the draft, the last answer, the check
// on its way and the last failure all come from outside (the R4 wiring); the only state here is the typed text. No
// address, storage or request. Every shown line is plain text from the API or fixed words, never Markdown or HTML.
export interface PlanDraftProps {
  plan: ProgramPlanDoc;
  // planRevisions[plan.plan_id]: the content version this answer must be for.
  planContentSha256: string;
  // The last successful answer (null: none yet); checked here before anything of it shows.
  answer: unknown;
  checking: boolean;
  failure: ApiFailure | null;
  onAdd: (text: string) => void;
  onRemove: (courseId: string) => void;
  onClear: () => void;
  onRetry: () => void;
  onViewCourse: (courseId: string) => void;
}

function Notices({ answer }: { answer: DraftAnswer }) {
  return answer.notices.map((n, i) => (
    <div key={i} className={styles.notice} data-level={n.level}>
      {n.level === 'warning' ? (
        <TriangleAlert aria-hidden="true" />
      ) : (
        <Info aria-hidden="true" />
      )}
      <div className={styles.noticeBody}>
        <p data-kind="notice" data-level={n.level}>
          {n.text}
        </p>
        {n.candidates.length > 0 && (
          <ul className={styles.candidates}>
            {n.candidates.map((c, j) => (
              <li key={j} data-kind="candidate">{`${c.code} · ${c.name}`}</li>
            ))}
          </ul>
        )}
        {n.candidates_omitted > 0 && (
          <p data-kind="note" className={styles.note}>
            {`另有 ${n.candidates_omitted} 个候选未展开。`}
          </p>
        )}
      </div>
    </div>
  ));
}

function Result({
  answer,
  plan,
  onRemove,
  onViewCourse,
}: {
  answer: DraftAnswer;
  plan: ProgramPlanDoc;
  onRemove: (courseId: string) => void;
  onViewCourse: (courseId: string) => void;
}) {
  const { met, missing, unknown } = answer.result.summary_counts;
  const lines = draftTreeLines(answer.result.root);
  return (
    <>
      <ul className={styles.courses}>
        {answer.courses.map((c) => (
          <li key={c.code} className={styles.course}>
            <p data-kind="course" className={styles.courseText}>
              {`${c.code} · ${c.name} · ${creditsText(c.credits)}`}
            </p>
            <div className={styles.courseActions}>
              <Button
                size="sm"
                data-kind="button"
                data-action="view"
                data-course-id={c.course_id}
                onClick={() => onViewCourse(c.course_id)}
              >
                {`${c.code} · 课程页／年度先修`}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                data-kind="button"
                data-action="remove"
                data-course-id={c.course_id}
                onClick={() => onRemove(c.course_id)}
              >
                {`移除 ${c.code}`}
              </Button>
            </div>
          </li>
        ))}
      </ul>
      <p data-kind="summary">
        {`按记录到的规则：${met} 组满足、${missing} 组还缺、${unknown} 组不确定。`}
      </p>
      {plan.coverage === 'partial' && (
        <p data-kind="note" className={styles.note}>
          这个方案只记录了部分规则；上述统计不是个人学位或注册审核。
        </p>
      )}
      <pre data-kind="tree" className={styles.tree}>
        {lines.map((line, i) => (
          <Fragment key={i}>
            {i > 0 && '\n'}
            <span data-line>{line}</span>
          </Fragment>
        ))}
      </pre>
      {answer.result.unplaced.length > 0 && (
        <>
          <p data-kind="unplaced" className={styles.text}>
            {`方案里没有写到：${answer.result.unplaced.join('、')}`}
          </p>
          <p data-kind="note" className={styles.note}>
            方案里没有写到这门课；不代表不能算，也不代表能算，请向项目核实。
          </p>
        </>
      )}
    </>
  );
}

function Alert({ kind, children }: { kind: string; children: string }) {
  return (
    <p data-kind={kind} role="alert" className={styles.alert}>
      {children}
    </p>
  );
}

export function PlanDraft(props: PlanDraftProps) {
  const [text, setText] = useState('');
  const inputId = useId();
  const headingId = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  const count = useRef<HTMLParagraphElement>(null);
  if (props.plan.review_status !== 'source_checked') return null;
  // A pressed button that goes away hands focus to a fixed place first (the course count, the heading), without
  // scrolling; one that stays keeps it (spec section 9).
  const focusFirst = (target: RefObject<HTMLElement | null>) =>
    target.current?.focus({ preventScroll: true });
  const parsed = props.answer === null ? null : parseDraftAnswer(props.answer);
  const answer =
    parsed?.kind === 'ok' &&
    parsed.answer.plan_content_sha256 === props.planContentSha256
      ? parsed.answer
      : null;
  return (
    <section aria-labelledby={headingId} className={styles.draft}>
      <h3 id={headingId} ref={heading} tabIndex={-1} data-kind="heading">
        我的选课草案（只在本次会话）
      </h3>
      <p data-kind="note" className={styles.note}>
        填写修过或打算修的课，只按填写课号解释已记录规则；不看成绩、免修、审批或开课学期，不判断能否注册或毕业。
      </p>
      <p data-kind="note" className={styles.note}>
        仅本次会话保存；刷新为新会话、登出或换账号后清空，不写数据库、不分享清单，也不交给聊天。
      </p>
      <p data-kind="note" className={styles.note}>
        学分按核对时的课程记录，不确认具体班次或个人学位计入。
      </p>
      <div>
        <Button
          data-kind="button"
          data-action="clear"
          onClick={() => {
            setText('');
            props.onClear();
          }}
        >
          清空草案
        </Button>
      </div>
      <div className={styles.field}>
        <label htmlFor={inputId}>
          课号（逗号、空格或换行分开，例如 CS 5010, CS 5800）
        </label>
        <textarea
          id={inputId}
          data-kind="textarea"
          rows={3}
          maxLength={DRAFT_INPUT_MAX}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      </div>
      <div className={styles.addRow}>
        {/* Not `disabled`: a disabled button drops the focus it has. */}
        <Button
          variant="primary"
          data-kind="button"
          data-action="add"
          aria-disabled={props.checking}
          className={styles.add}
          onClick={() => {
            if (!props.checking) props.onAdd(text);
          }}
        >
          加入草案
        </Button>
        <div role="status" className={styles.live}>
          {props.checking && <span data-kind="status">正在核对课程…</span>}
        </div>
      </div>
      {props.failure && (
        <div className={styles.failure}>
          <Alert kind="failure">{draftFailureMessage(props.failure)}</Alert>
          {canRetryDraft(props.failure) && (
            <Button
              data-kind="button"
              data-action="retry"
              onClick={() => {
                focusFirst(heading);
                props.onRetry();
              }}
            >
              重新核对
            </Button>
          )}
        </div>
      )}
      {parsed?.kind === 'invalid' && (
        <Alert kind="warning">草案结果的格式不对，没有显示。</Alert>
      )}
      {parsed?.kind === 'ok' && !answer && (
        <Alert kind="warning">
          草案结果与当前所选方案的内容版本不一致；请刷新方案后重试，未显示旧结果。
        </Alert>
      )}
      {/* Always there, so a screen reader hears what a check changed while focus stays on the button pressed. */}
      <div aria-live="polite" className={`${styles.live} ${styles.stack}`}>
        {answer && (
          <>
            <Notices answer={answer} />
            <p ref={count} tabIndex={-1} data-kind="count">
              {`已填 ${answer.courses.length}/${MAX_DRAFT_COURSES} 门（不区分已修与打算修）`}
            </p>
          </>
        )}
      </div>
      {answer && (
        <Result
          answer={answer}
          plan={props.plan}
          onRemove={(id) => {
            focusFirst(count);
            props.onRemove(id);
          }}
          onViewCourse={props.onViewCourse}
        />
      )}
    </section>
  );
}
