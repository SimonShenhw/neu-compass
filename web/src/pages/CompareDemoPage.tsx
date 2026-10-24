import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  activateCompareCase,
  compareCaseOptions,
  demoColumns,
  demoList,
  readCompareCase,
} from '../fixtures/compareDemo';
import type { CompareDemoCase } from '../fixtures/compareDemo';
import type { CompareColumn } from '../api/course';
import { resolveColumn } from '../models/compare';
import { useList } from '../models/compareList';
import { ComparePage } from './ComparePage';
import styles from './ComparePage.module.css';

function DemoContent({ scenario }: { scenario: CompareDemoCase }) {
  const ids = useList(demoList);
  const [retrying, setRetrying] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    activateCompareCase(scenario);
  }, [scenario]);
  useEffect(
    () => () => {
      if (timer.current !== null) clearTimeout(timer.current);
    },
    [],
  );
  const original = demoColumns(scenario);
  const columns: Record<string, CompareColumn> = Object.fromEntries(
    Object.entries(original).map(([id, column]) => [
      id,
      retrying && resolveColumn(column).status === 'error'
        ? { status: 'loading' }
        : column,
    ]),
  );
  return (
    <ComparePage
      ids={ids}
      columns={columns}
      onRemove={demoList.remove}
      onClear={demoList.clear}
      onReload={() => {
        if (timer.current !== null) clearTimeout(timer.current);
        setRetrying(true);
        timer.current = setTimeout(() => {
          timer.current = null;
          setRetrying(false);
        }, 400);
      }}
    />
  );
}
export function CompareDemoPage() {
  const [params, setParams] = useSearchParams();
  const scenario = readCompareCase(params.get('case'));
  return (
    <>
      <section aria-label="对比演示设置" className={styles.demo}>
        <label>
          演示场景
          <select
            value={scenario}
            onChange={(event) => {
              const next = new URLSearchParams(params);
              next.set('case', readCompareCase(event.target.value));
              void setParams(next, { replace: true });
            }}
          >
            {compareCaseOptions.map((value) => (
              <option value={value} key={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <p>
          合成 API
          数据，不发请求。演示首次进入或切换场景会填入示例课程；刷新也会重新填入，不代表列表持久化。演示用自己的列表，不动「课程对比」里加的课，侧栏的数字也不跟着变。
        </p>
      </section>
      <DemoContent key={scenario} scenario={scenario} />
    </>
  );
}
