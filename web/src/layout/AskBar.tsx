import { ArrowUp, LockKeyhole } from 'lucide-react';
import { useId, useState } from 'react';
import { Link } from 'react-router-dom';
import { IconButton } from '../components/IconButton';
import styles from './AskBar.module.css';

export function AskBar({
  onSend,
}: {
  onSend: (question: string, allowSave: boolean) => void;
}) {
  const [text, setText] = useState('');
  const [allowSave, setAllowSave] = useState(false);
  const privacyId = useId();
  function send() {
    if (text.trim()) {
      onSend(text.trim(), allowSave);
      setText('');
      setAllowSave(false);
    }
  }
  return (
    <form
      className={styles.askBar}
      aria-label="提问"
      onSubmit={(event) => {
        event.preventDefault();
        send();
      }}
    >
      <p className={styles.privacy} id={privacyId}>
        <LockKeyhole aria-hidden="true" />
        <span>
          你的提问原文会记进不公开的查询日志。请不要输入个人信息或密码之类的秘密。留多久、怎么删，见{' '}
          <Link to="/privacy" aria-label="数据与隐私">
            数据与隐私。
          </Link>
        </span>
      </p>
      <div className={styles.input}>
        <label className="visually-hidden" htmlFor={`${privacyId}-query`}>
          课程问题
        </label>
        <textarea
          id={`${privacyId}-query`}
          rows={1}
          value={text}
          onChange={(event) => setText(event.target.value)}
          aria-describedby={privacyId}
          placeholder="问任何课程问题…"
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
          disabled={!text.trim()}
        >
          <ArrowUp aria-hidden="true" />
        </IconButton>
      </div>
      <label className={styles.optin}>
        <input
          type="checkbox"
          checked={allowSave}
          onChange={(event) => setAllowSave(event.target.checked)}
        />
        允许保存这次的回答和评价（默认不保存）
      </label>
    </form>
  );
}
