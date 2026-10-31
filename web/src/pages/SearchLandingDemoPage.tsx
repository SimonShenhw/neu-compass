import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { LandingDemoConversation } from '../features/search-landing/LandingDemoConversation';
import { useLandingDemo } from '../features/search-landing/useLandingDemo';
import {
  landingOptions,
  landingScenarios,
  sampleChat,
} from '../fixtures/landingDemo';
import { demoSource } from '../fixtures/searchDemo';
import { SAMPLE_QUESTIONS } from '../models/landing';
import styles from '../features/search-landing/SearchLanding.module.css';

function DemoSession({
  options,
  reset,
}: {
  options: ReturnType<typeof landingOptions>;
  reset: () => void;
}) {
  const data = useLandingDemo(options.scenario, options.speed);
  const [notice, setNotice] = useState('');
  return (
    <>
      <LandingDemoConversation
        {...data}
        onReset={reset}
        onOpenProgram={(id) => setNotice(`演示：这里会打开培养方案 ${id}`)}
        onViewCourse={(id) => setNotice(`演示：这里会打开 ${id}`)}
        onOpenCoop={() => setNotice('演示：这里会去 Co-op 页')}
        onFollowUp={(text) => setNotice(`演示：这里会接着问「${text}」`)}
        sourceFor={(query) =>
          demoSource(
            sampleChat(SAMPLE_QUESTIONS.findIndex((q) => q.query === query)),
            'normal',
            true,
          )
        }
      />
      <p role="status" aria-label="落地页演示结果">
        {notice}
      </p>
    </>
  );
}
export default function SearchLandingDemoPage() {
  const [params, setParams] = useSearchParams();
  const options = landingOptions(params);
  const [replay, setReplay] = useState(0);
  const page = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (replay > 0) page.current?.focus({ preventScroll: true });
  }, [replay]);
  return (
    <div
      ref={page}
      tabIndex={-1}
      className={styles.demo}
      aria-label="落地页演示"
    >
      <section className={styles.controls} aria-label="落地演示设置">
        <label>
          数据
          <select
            value={options.scenario}
            onChange={(e) => {
              const next = new URLSearchParams(params);
              next.set('scenario', e.target.value);
              void setParams(next, { replace: true });
            }}
          >
            {landingScenarios.map((name) => (
              <option value={name} key={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <label>
          速度
          <select
            value={options.speed}
            onChange={(e) => {
              const next = new URLSearchParams(params);
              next.set('speed', e.target.value);
              void setParams(next, { replace: true });
            }}
          >
            {[
              ['normal', '正常'],
              ['slow', '慢'],
              ['instant', '立即'],
              ['forever', '一直加载'],
            ].map(([value, label]) => (
              <option value={value} key={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </section>
      <DemoSession
        key={`${options.scenario}:${options.speed}:${replay}`}
        options={options}
        reset={() => setReplay((n) => n + 1)}
      />
    </div>
  );
}
