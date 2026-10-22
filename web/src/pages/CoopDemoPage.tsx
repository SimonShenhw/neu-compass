import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  demoList,
  demoOutcome,
  demoViewer,
  listOptions,
  readViewer,
  submitOptions,
  viewerOptions,
} from '../fixtures/coopDemo';
import { CoopPage } from './CoopPage';
import styles from './CoopPage.module.css';

// Local-only routing adapter. No HTTP client, auth, storage, or contribution updates.
export function CoopDemoPage() {
  const [params, setParams] = useSearchParams();
  const [notice, setNotice] = useState('');
  const viewer = readViewer(params.get('viewer'));
  const list = listOptions.some((option) => option.value === params.get('list'))
    ? params.get('list')!
    : 'ready';
  const submit = submitOptions.some(
    (option) => option.value === params.get('submit'),
  )
    ? params.get('submit')!
    : 'pending';
  function choose(name: string, value: string) {
    const next = new URLSearchParams(params);
    next.delete('demo');
    next.set(name, value);
    setNotice('');
    void setParams(next, { replace: true });
  }
  return (
    <>
      <section className={styles.demo} aria-label="Co-op 演示设置">
        <p>
          合成数据演示 · 不接真实登录，不保存或发送投稿；演示参数不是权限控制。
        </p>
        {(
          [
            ['viewer', '演示访客', viewer, viewerOptions],
            ['list', '演示列表', list, listOptions],
            ['submit', '演示提交结果', submit, submitOptions],
          ] as const
        ).map(([name, label, value, options]) => (
          <label key={name}>
            {label}
            <select
              value={value}
              onChange={(event) => choose(name, event.target.value)}
            >
              {options.map((option) => (
                <option value={option.value} key={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        ))}
        <p role="status" aria-label="演示提示">
          {notice}
        </p>
      </section>
      <CoopPage
        key={`${viewer}:${list}:${submit}`}
        viewer={demoViewer(viewer)}
        list={demoList(viewer, list)}
        onRetryList={() => choose('list', 'ready')}
        onLogin={() =>
          setNotice('演示模式：未发起真实登录。R2 接入后将使用真实登录回调。')
        }
        onSubmit={async () => {
          await new Promise<void>((resolve) => window.setTimeout(resolve, 400));
          return demoOutcome(submit);
        }}
      />
    </>
  );
}
