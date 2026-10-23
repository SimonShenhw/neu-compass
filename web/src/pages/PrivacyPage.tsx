import { useEffect, useRef, useState } from 'react';
import type { PrivacyPageProps } from '../api/privacy';
import { AccountDeletion } from '../components/AccountDeletion';
import { Button } from '../components/Button';
import { deletionNotice, privacyContent } from '../models/privacy';
import styles from './PrivacyPage.module.css';

export function PrivacyPage({
  viewer,
  privacy,
  onRetry,
  onDelete,
  onSignedOut,
}: PrivacyPageProps) {
  // Deliberately outside AccountDeletion: signout unmounts the form, not this result.
  const [notice, setNotice] = useState<{ message: string } | null>(null);
  const result = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (notice) result.current?.focus();
  }, [notice]);
  if (privacy.status === 'loading') return <p role="status">正在加载</p>;
  const body = privacy.status === 'ready' ? privacyContent(privacy.body) : null;
  if (!body)
    return (
      <section className={styles.failure} aria-label="隐私说明加载失败">
        <p>隐私说明暂时加载不了，请稍后重试。</p>
        <Button onClick={() => onRetry()}>重试</Button>
      </section>
    );
  return (
    <section className={styles.page} aria-label="数据与隐私内容">
      <p className={styles.intro}>{body.intro}</p>
      {notice && (
        <div
          role="status"
          aria-label="删除结果"
          tabIndex={-1}
          ref={result}
          className={styles.result}
        >
          <p>{notice.message}</p>
        </div>
      )}
      <div className={styles.sections}>
        {body.sections.map((section, index) => (
          <section className={styles.policy} key={index}>
            <h2>{section.heading}</h2>
            <ul>
              {section.sentences.map((sentence, i) => (
                <li key={i}>{sentence}</li>
              ))}
            </ul>
          </section>
        ))}
      </div>
      {viewer.kind === 'member' && (
        <AccountDeletion
          explanation={body.delete_what}
          onDelete={onDelete}
          onStart={() => setNotice(null)}
          onOutcome={(outcome) => {
            const next = deletionNotice(outcome);
            setNotice({ message: next.message });
            if (next.signedOut) onSignedOut();
          }}
        />
      )}
    </section>
  );
}
