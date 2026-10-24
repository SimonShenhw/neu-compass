import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import type { Load } from '../api/load';
import { ProgramList } from '../features/programs/ProgramList';
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

function PolicyRequest({
  name,
  speed,
  ...props
}: Omit<ProgramCurriculumProps, 'policies'> & {
  name: string | null;
  speed: string;
}) {
  const policies = useProgramDemoLoad(name, speed);
  return <ProgramCurriculum {...props} policies={policies} />;
}
function DemoCurriculum({
  spec,
  speed,
  ...props
}: Omit<
  ProgramCurriculumProps,
  | 'curriculum'
  | 'policies'
  | 'programId'
  | 'publicBaseUrl'
  | 'planRevisions'
  | 'planRevised'
> & { spec: Extract<ProgramScenario, { view: 'curriculum' }>; speed: string }) {
  const curriculum = useProgramDemoLoad(spec.curriculum, speed) as Load;
  const name =
    props.selectedPlanId === null
      ? null
      : props.selectedPlanId === spec.selectedPlanId && spec.policies
        ? spec.policies
        : defaultProgramPolicy(props.selectedPlanId);
  return (
    <PolicyRequest
      key={`${props.selectedPlanId}:${name}`}
      name={name}
      speed={speed}
      {...props}
      curriculum={curriculum}
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
  ...props
}: {
  name: string;
  speed: string;
  onOpenProgram: (id: string) => void;
  onRetry: () => void;
}) {
  const programs = useProgramDemoLoad(name, speed) as Load;
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
  const [selected, setSelected] = useState(
    initial.view === 'curriculum' ? initial.selectedPlanId : null,
  );
  const [replay, setReplay] = useState(0);
  const [notice, setNotice] = useState('');
  const open = (id: string) => {
    const name = `curriculum-${id}`;
    setSelected(null);
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
  };
  return (
    <>
      {spec.view === 'list' ? (
        <DemoList
          key={`list:${replay}`}
          name={spec.programs}
          speed={speed}
          onOpenProgram={open}
          onRetry={() => setReplay((n) => n + 1)}
        />
      ) : (
        <DemoCurriculum
          key={`${spec.curriculum}:${replay}`}
          spec={spec}
          speed={speed}
          selectedPlanId={selected}
          onSelectPlan={setSelected}
          onBack={() => {
            setSpec({ view: 'list', programs: 'programs' });
            setSelected(null);
            setNotice('');
          }}
          onRefresh={() => {
            setSelected(null);
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
