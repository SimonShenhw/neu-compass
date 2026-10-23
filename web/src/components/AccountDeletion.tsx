import { useEffect, useId, useRef, useState } from 'react';
import type { DeleteOutcome, PrivacyPageProps } from '../api/privacy';
import { Button } from './Button';
import styles from '../pages/PrivacyPage.module.css';

export function AccountDeletion({
  explanation,
  onDelete,
  onStart,
  onOutcome,
}: Pick<PrivacyPageProps, 'onDelete'> & {
  explanation: string;
  onStart: () => void;
  onOutcome: (outcome: DeleteOutcome) => void;
}) {
  const title = useId();
  const [confirmed, setConfirmed] = useState(false);
  const [pending, setPending] = useState(false);
  const locked = useRef(false);
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  async function submit() {
    if (!confirmed || locked.current) return;
    locked.current = true;
    setPending(true);
    onStart();
    let outcome: DeleteOutcome;
    try {
      outcome = await onDelete();
    } catch {
      outcome = { ok: false, status: null };
    }
    if (!active.current) return;
    locked.current = false;
    setPending(false);
    onOutcome(outcome);
  }
  return (
    <section className={styles.deletion} aria-labelledby={title}>
      <h2 id={title}>删除我的账号和投稿</h2>
      <p>{explanation}</p>
      <form
        aria-label="删除我的账号和投稿"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <label className={styles.confirm}>
          <input
            type="checkbox"
            checked={confirmed}
            disabled={pending}
            onChange={(event) => setConfirmed(event.target.checked)}
          />
          我知道删除以后不能恢复
        </label>
        <Button type="submit" disabled={!confirmed || pending}>
          {pending ? '正在删除…' : '删除我的账号和投稿'}
        </Button>
      </form>
    </section>
  );
}
