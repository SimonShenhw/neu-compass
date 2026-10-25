import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import type { Load } from '../api/load';
import {
  ProgramList,
  type ProgramListProps,
} from '../features/programs/ProgramList';
import {
  ProgramCurriculum,
  type ProgramCurriculumProps,
} from '../features/programs/ProgramCurriculum';
import { useProgramDemoLoad } from '../features/programs/useProgramDemoLoad';
import {
  defaultProgramPolicy,
  programFixture,
  programsOptions,
  type ProgramScenario,
} from '../fixtures/programsDemo';
import { programScenarios } from '../fixtures/programsScenarios';
import styles from '../features/programs/Programs.module.css';

function DemoCurriculum({
  spec,
  speed,
  replay,
  pick,
  ...props
}: Omit<
  ProgramCurriculumProps,
  | 'curriculum'
  | 'policies'
  | 'programId'
  | 'publicBaseUrl'
  | 'planRevisions'
  | 'planRevised'
> & {
  spec: Extract<ProgramScenario, { view: 'curriculum' }>;
  speed: string;
  replay: number;
  pick: number;
}) {
  const curriculum = useProgramDemoLoad(spec.curriculum, speed, replay) as Load;
  const name =
    props.selectedPlanId === null
      ? null
      : props.selectedPlanId === spec.selectedPlanId && spec.policies
        ? spec.policies
        : defaultProgramPolicy(props.selectedPlanId);
  const policies = useProgramDemoLoad(name, speed, pick);
  return (
    <ProgramCurriculum
      {...props}
      curriculum={curriculum}
      policies={policies}
      programId={spec.programId}
      publicBaseUrl={spec.publicBaseUrl}
      planRevisions={spec.planRevisions}
      planRevised={spec.planRevised}
    />
  );
}
function DemoList({
  name,
  speed,
  replay,
  ...props
}: Omit<ProgramListProps, 'programs'> & {
  name: string;
  speed: string;
  replay: number;
}) {
  const programs = useProgramDemoLoad(name, speed, replay) as Load;
  return <ProgramList {...props} programs={programs} />;
}
function DemoSession({
  initial,
  speed,
}: {
  initial: ProgramScenario;
  speed: string;
}) {
  const [spec, setSpec] = useState(initial);
  // Every choice reads its policies again (pick), even for a plan chosen before; refresh and retry replay in place.
  const [selection, setSelection] = useState({
    planId: initial.view === 'curriculum' ? initial.selectedPlanId : null,
    pick: 0,
  });
  const [replay, setReplay] = useState(0);
  const [notice, setNotice] = useState('');
  // Opening a program, going back and retrying take away the pressed button: focus goes to the view now shown.
  const view = useRef<HTMLElement>(null);
  const [moved, setMoved] = useState(0);
  useEffect(() => {
    if (moved > 0) view.current?.focus({ preventScroll: true });
  }, [moved]);
  const select = (planId: string | null) =>
    setSelection((s) => ({ planId, pick: s.pick + 1 }));
  const open = (id: string) => {
    const name = `curriculum-${id}`;
    select(null);
    setNotice('');
    setSpec({
      view: 'curriculum',
      programId: id,
      curriculum: name,
      selectedPlanId: null,
      policies: null,
      planRevised: false,
      publicBaseUrl: 'https://compass.example.test',
      planRevisions: programFixture(name).proposed_plan_revisions ?? {},
    });
    setMoved((n) => n + 1);
  };
  return (
    <>
      {spec.view === 'list' ? (
        <DemoList
          ref={view}
          name={spec.programs}
          speed={speed}
          replay={replay}
          onOpenProgram={open}
          onRetry={() => {
            setReplay((n) => n + 1);
            setMoved((n) => n + 1);
          }}
        />
      ) : (
        <DemoCurriculum
          key={spec.curriculum}
          ref={view}
          spec={spec}
          speed={speed}
          replay={replay}
          pick={selection.pick}
          selectedPlanId={selection.planId}
          onSelectPlan={select}
          onBack={() => {
            setSpec({ view: 'list', programs: 'programs' });
            select(null);
            setNotice('');
            setMoved((n) => n + 1);
          }}
          onRefresh={() => {
            select(null);
            setSpec({ ...spec, planRevised: false });
            setReplay((n) => n + 1);
          }}
          onViewCourse={(id) => setNotice(`演示：这里会打开 ${id}`)}
        />
      )}
      <p role="status" aria-label="培养方案演示结果">
        {notice}
      </p>
    </>
  );
}
export default function ProgramsDemoPage() {
  const [params, setParams] = useSearchParams();
  const options = programsOptions(params);
  const change = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    next.set(key, value);
    void setParams(next, { replace: true });
  };
  return (
    <div className={styles.demo} aria-label="培养方案演示">
      <section className={styles.controls} aria-label="培养方案演示设置">
        <label>
          场景
          <select
            value={options.scenario}
            onChange={(e) => change('scenario', e.target.value)}
          >
            {Object.keys(programScenarios).map((s) => (
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
            {[
              ['normal', '正常'],
              ['slow', '慢'],
              ['instant', '立即'],
              ['forever', '一直加载'],
            ].map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>
      </section>
      <DemoSession
        key={`${options.scenario}:${options.speed}`}
        initial={programScenarios[options.scenario]}
        speed={options.speed}
      />
    </div>
  );
}
