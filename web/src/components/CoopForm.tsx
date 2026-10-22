import { useEffect, useId, useRef, useState } from 'react';
import type { ChangeEvent } from 'react';
import type { CoopPageProps } from '../api/coop';
import {
  emptyDraft,
  errorField,
  failureMessage,
  fieldLabels,
  industryLabels,
  invalidMessage,
  outcomeMessages,
  prepareSubmission,
} from '../models/coop';
import type { CoopDraft, CoopField, FieldErrors } from '../models/coop';
import { Button } from './Button';
import styles from './CoopForm.module.css';

type Notice = { message: string; coopId?: string; login?: boolean };
const fields = Object.keys(fieldLabels) as CoopField[];
const paragraphs: readonly CoopField[] = [
  'interview_summary',
  'technical_questions',
  'salary_range_usd',
];

export function CoopForm({
  onSubmit,
  onLogin,
}: Pick<CoopPageProps, 'onSubmit' | 'onLogin'>) {
  const prefix = useId();
  const [draft, setDraft] = useState<CoopDraft>({ ...emptyDraft });
  const [errors, setErrors] = useState<FieldErrors>({});
  const [notice, setNotice] = useState<Notice | null>(null);
  const [pending, setPending] = useState(false);
  const locked = useRef(false);
  const active = useRef(true);
  const result = useRef<HTMLDivElement>(null);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  useEffect(() => {
    if (notice) result.current?.focus();
  }, [notice]);
  function change(name: CoopField, value: string) {
    setDraft((current) => ({ ...current, [name]: value }));
    setErrors((current) => {
      const next = { ...current };
      delete next[name];
      return next;
    });
  }
  async function submit(durationBadInput: boolean) {
    if (locked.current) return;
    const prepared = prepareSubmission(draft, durationBadInput);
    setErrors(prepared.errors);
    if (!prepared.request) {
      setNotice({ message: '请检查标出的字段后再提交。' });
      return;
    }
    locked.current = true;
    setPending(true);
    setNotice(null);
    try {
      const outcome = await onSubmit(prepared.request);
      if (!active.current) return;
      if (outcome.ok) {
        setNotice({
          message: `${outcome.result.duplicate ? '重复提交，保留原记录（内容未替换）。' : ''}${outcomeMessages[outcome.result.status]}`,
          coopId: outcome.result.coop_id,
        });
        setDraft({ ...emptyDraft });
      } else {
        setNotice({
          message: failureMessage(outcome.status, outcome.body !== null),
          login: outcome.status === 401,
        });
        const name =
          outcome.status === 422 ? errorField(outcome.body?.detail) : null;
        if (name) setErrors({ [name]: invalidMessage });
      }
    } catch {
      if (active.current) setNotice({ message: failureMessage(503, false) });
    } finally {
      if (active.current) {
        locked.current = false;
        setPending(false);
      }
    }
  }
  return (
    <section className={styles.panel} aria-labelledby={`${prefix}-title`}>
      <h2 id={`${prefix}-title`}>分享你的 Co-op 经验</h2>
      <p className={styles.hint}>
        投稿先私有收集，审核并公开后才可能获得贡献奖励。请勿填写姓名、联系方式等个人信息。
      </p>
      {notice && (
        <div
          role="status"
          aria-label="投稿结果"
          tabIndex={-1}
          ref={result}
          className={styles.result}
        >
          <p>{notice.message}</p>
          {notice.coopId && (
            <p className={styles.identifier}>
              记录编号：<code>{notice.coopId}</code>
            </p>
          )}
          {notice.login && <Button onClick={() => onLogin()}>登录</Button>}
        </div>
      )}
      <form
        aria-label="分享你的 Co-op 经验"
        noValidate
        autoComplete="off"
        onSubmit={(event) => {
          event.preventDefault();
          // An incomplete number such as "1e" has value="" but is not blank.
          // Read at submit time; React state alone loses that editing buffer.
          const duration =
            event.currentTarget.elements.namedItem('duration_months');
          void submit(
            duration instanceof HTMLInputElement && duration.validity.badInput,
          );
        }}
      >
        <fieldset disabled={pending} className={styles.fields}>
          <legend className="visually-hidden">Co-op 经验字段</legend>
          {fields.map((name) => {
            const id = `${prefix}-${name}`;
            const common = {
              id,
              name,
              value: draft[name],
              'aria-invalid': Boolean(errors[name]),
              'aria-describedby': errors[name] ? `${id}-error` : undefined,
              onChange: (
                event: ChangeEvent<
                  HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement
                >,
              ) => change(name, event.target.value),
            };
            return (
              <div
                key={name}
                className={`${styles.field} ${paragraphs.includes(name) || name === 'related_courses' ? styles.full : ''}`}
              >
                <label htmlFor={id}>{fieldLabels[name]}</label>
                {name === 'industry' ? (
                  <select {...common}>
                    <option value="">不填</option>
                    {Object.entries(industryLabels).map(([value, label]) => (
                      <option value={value} key={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                ) : paragraphs.includes(name) ? (
                  <textarea
                    {...common}
                    rows={name === 'salary_range_usd' ? 2 : 4}
                  />
                ) : (
                  <input
                    {...common}
                    type={name === 'duration_months' ? 'number' : 'text'}
                    {...(name === 'duration_months'
                      ? { min: 1, max: 8, step: 1 }
                      : {})}
                    required={name === 'company' || name === 'role'}
                  />
                )}
                {errors[name] && (
                  <p id={`${id}-error`} className={styles.error}>
                    {errors[name]}
                  </p>
                )}
              </div>
            );
          })}
        </fieldset>
        <Button type="submit" variant="primary" disabled={pending}>
          {pending ? '提交中' : '提交经验'}
        </Button>
      </form>
    </section>
  );
}
