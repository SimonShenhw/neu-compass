import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { PlanDraft } from '../features/programs/PlanDraft';
import {
  DRAFT_SPEEDS,
  draftDelay,
  draftOptions,
  draftPlan,
  draftState,
  type DraftScenario,
  type DraftSpeed,
} from '../fixtures/draftDemo';
import { draftScenarios } from '../fixtures/draftScenarios';
import { scopeLabel } from '../models/programFormat';
import styles from '../features/programs/Programs.module.css';
import draftStyles from '../features/programs/PlanDraft.module.css';

const CHECKING = { answer: null, checking: true, failure: null };

// One run of a scene: the first check is on its way, then the scene's own props arrive (a scene that is itself
// checking stays so). The callbacks only say what the real page would do; the answer never changes here.
function DraftDemoSession({
  spec,
  speed,
}: {
  spec: DraftScenario;
  speed: DraftSpeed;
}) {
  const plan = draftPlan(spec.plan);
  const [arrived, setArrived] = useState(false);
  const [notice, setNotice] = useState('');
  useEffect(() => {
    const delay = draftDelay(speed);
    if (delay === null) return;
    const timer = setTimeout(() => setArrived(true), delay);
    return () => clearTimeout(timer);
  }, [speed]);
  return (
    <>
      <h2 className={draftStyles.scope}>{scopeLabel(plan)}</h2>
      <PlanDraft
        plan={plan}
        planContentSha256={spec.planContentSha256}
        {...(arrived ? draftState(spec) : CHECKING)}
        onAdd={(text) => setNotice(`演示：加入「${text}」`)}
        onRemove={(id) => setNotice(`演示：移除 ${id}`)}
        onClear={() => setNotice('演示：清空草案')}
        onRetry={() => setNotice('演示：重新核对')}
        onViewCourse={(id) => setNotice(`演示：这里会打开 ${id}`)}
      />
      <p role="status" aria-label="选课草案演示结果">
        {notice}
      </p>
    </>
  );
}

export default function PlanDraftDemoPage() {
  const [params, setParams] = useSearchParams();
  const options = draftOptions(params);
  const change = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    next.set(key, value);
    void setParams(next, { replace: true });
  };
  return (
    <div className={styles.demo}>
      <section className={styles.controls} aria-label="选课草案演示设置">
        <label>
          场景
          <select
            value={options.scenario}
            onChange={(e) => change('scenario', e.target.value)}
          >
            {Object.keys(draftScenarios).map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label>
          速度
          <select
            value={options.speed}
            onChange={(e) => change('speed', e.target.value)}
          >
            {DRAFT_SPEEDS.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>
      </section>
      <DraftDemoSession
        key={`${options.scenario}:${options.speed}`}
        spec={draftScenarios[options.scenario]}
        speed={options.speed}
      />
    </div>
  );
}
