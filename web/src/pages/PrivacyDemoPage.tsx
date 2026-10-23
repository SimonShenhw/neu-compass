import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  deleteOptions,
  demoDeletion,
  demoPrivacy,
  privacyOptions,
  privacyViewerOptions,
  readChoice,
} from '../fixtures/privacyDemo';
import type {
  DeleteDemoChoice,
  PrivacyDemoChoice,
} from '../fixtures/privacyDemo';
import { PrivacyPage } from './PrivacyPage';
import styles from './PrivacyPage.module.css';

function PrivacyDemoSession({
  initialViewer,
  policy,
  deletion,
}: {
  initialViewer: 'guest' | 'member';
  policy: PrivacyDemoChoice;
  deletion: DeleteDemoChoice;
}) {
  const [kind, setKind] = useState(initialViewer);
  const [retrying, setRetrying] = useState(false);
  const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (retryTimer.current !== null) clearTimeout(retryTimer.current);
    },
    [],
  );
  return (
    <>
      <p className={styles.viewer} role="status" aria-label="当前演示访客">
        当前演示状态：{kind === 'member' ? '已登录（合成）' : '游客'}
      </p>
      <PrivacyPage
        viewer={{ kind }}
        privacy={retrying ? { status: 'loading' } : demoPrivacy(policy)}
        onRetry={() => {
          if (retryTimer.current !== null) clearTimeout(retryTimer.current);
          setRetrying(true);
          retryTimer.current = setTimeout(() => {
            retryTimer.current = null;
            setRetrying(false);
          }, 400);
        }}
        onDelete={async () => {
          await new Promise<void>((resolve) => window.setTimeout(resolve, 400));
          return demoDeletion(deletion);
        }}
        onSignedOut={() => setKind('guest')}
      />
    </>
  );
}
// URL changes explicitly start a new demo. Signout changes only session state, never this key.
export function PrivacyDemoPage() {
  const [params, setParams] = useSearchParams();
  const viewer = readChoice(params.get('viewer'), privacyViewerOptions);
  const policy = readChoice(params.get('privacy'), privacyOptions);
  const deletion = readChoice(params.get('delete'), deleteOptions);
  return (
    <>
      <section className={styles.demo} aria-label="隐私演示设置">
        <p>
          合成 API
          数据演示，不发请求、不执行真实删号或登录；网址中的访客只用于初始化场景。
        </p>
        {(
          [
            ['viewer', '演示访客', viewer, privacyViewerOptions],
            ['privacy', '演示隐私说明', policy, privacyOptions],
            ['delete', '演示删除结果', deletion, deleteOptions],
          ] as const
        ).map(([name, label, value, options]) => (
          <label key={name}>
            {label}
            <select
              value={value}
              onChange={(event) => {
                const next = new URLSearchParams(params);
                next.set(name, event.target.value);
                void setParams(next, { replace: true });
              }}
            >
              {options.map((option) => (
                <option value={option} key={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>
        ))}
      </section>
      <PrivacyDemoSession
        key={`${viewer}:${policy}:${deletion}`}
        initialViewer={viewer}
        policy={policy}
        deletion={deletion}
      />
    </>
  );
}
