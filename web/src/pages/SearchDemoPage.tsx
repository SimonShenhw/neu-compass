import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Button } from '../components/Button';
import { SearchConversation } from '../features/search-answer/SearchConversation';
import { useConversation } from '../features/search-answer/useConversation';
import {
  demoFeedback,
  demoOptions,
  demoSource,
  searchCases,
  searchFixture,
  searchSequence,
} from '../fixtures/searchDemo';
import styles from '../features/search-answer/SearchConversation.module.css';

type Options = ReturnType<typeof demoOptions>;
function DemoSession({ options }: { options: Options }) {
  const { turns, busy, ask } = useConversation();
  const [notice, setNotice] = useState('');
  const names = searchSequence(options.caseName),
    next = names[turns.length];
  useEffect(() => {
    let live = true;
    if (!busy && next)
      queueMicrotask(() => {
        if (!live) return;
        const fixture = searchFixture(next);
        ask({
          question: fixture.request.body.query,
          allowSave: fixture.request.body.allow_feedback_capture === true,
          source: demoSource(fixture, options.speed, options.reason === 'on'),
        });
      });
    return () => {
      live = false;
    };
  }, [busy, next, ask, options.speed, options.reason]);
  return (
    <>
      <p className={styles.note}>
        {names.length === 1
          ? searchFixture(names[0]!).notes
          : '固定合成多轮对话，按顺序播放；不请求后端。'}
      </p>
      <SearchConversation
        turns={turns}
        busy={busy}
        feedbackEnabled={options.feedback === 'on'}
        onViewCourse={(id) => setNotice(`演示：这里会打开 ${id}`)}
        onFollowUp={(text) => setNotice(`演示：这里会接着问「${text}」`)}
        onFeedback={(vote) => demoFeedback(vote, options.vote)}
      />
      <p role="status" aria-label="搜索演示结果">
        {notice}
      </p>
    </>
  );
}
export default function SearchDemoPage() {
  const [params, setParams] = useSearchParams();
  const options = demoOptions(params);
  const [replay, setReplay] = useState(0);
  const fields = [
    {
      name: 'case',
      label: '演示对话',
      value: options.caseName,
      values: searchCases.map((name) => [name, name]),
    },
    {
      name: 'feedback',
      label: '回答反馈',
      value: options.feedback,
      values: [
        ['off', '关'],
        ['on', '开'],
      ],
    },
    {
      name: 'reason',
      label: '409 带 reason',
      value: options.reason,
      values: [
        ['on', '带'],
        ['off', '不带'],
      ],
    },
    {
      name: 'vote',
      label: '点评价时',
      value: options.vote,
      values: [
        ['saved', '保存成功'],
        ['404', '凭证过期 404'],
        ['503', '暂时不可用 503'],
        ['mismatch', '回来的对不上'],
      ],
    },
    {
      name: 'speed',
      label: '速度',
      value: options.speed,
      values: [
        ['normal', '正常'],
        ['slow', '慢'],
        ['instant', '立即'],
      ],
    },
  ];
  return (
    <div className={styles.demo}>
      <section className={styles.controls} aria-label="搜索演示设置">
        {fields.map((field) => (
          <label key={field.name}>
            {field.label}
            <select
              value={field.value}
              onChange={(e) => {
                const next = new URLSearchParams(params);
                next.set(field.name, e.target.value);
                void setParams(next, { replace: true });
              }}
            >
              {field.values.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        ))}
        <Button variant="primary" onClick={() => setReplay((n) => n + 1)}>
          开始
        </Button>
      </section>
      <DemoSession
        key={`${Object.values(options).join(':')}:${replay}`}
        options={options}
      />
    </div>
  );
}
