import { ArrowLeft } from 'lucide-react';
import type { ReactNode, Ref } from 'react';
import type { Load } from '../../api/load';
import { Button } from '../../components/Button';
import { CourseCode } from '../../components/CourseCode';
import { Select } from '../../components/Select';
import { parseCurriculum } from '../../models/programs';
import { availablePlans } from '../../models/programPlans';
import { hash } from '../../models/programGuard';
import { oneLine } from '../../models/courseDetailFormat';
import { programRuleLines } from '../../models/requisiteRules';
import {
  apiErrorMessage,
  collapseSpace,
  PLAN_LABEL,
  PLAN_PLACEHOLDER,
  PROGRAM_INTRO,
  requirementLabel,
  scopeLabel,
  semesterHeading,
  shareUrl,
} from '../../models/programFormat';
import { Disclosure, Line, SourceLink } from './ProgramParts';
import { ProgramPolicies } from './ProgramPolicies';
import styles from './Programs.module.css';

export interface ProgramCurriculumProps {
  programId: string;
  curriculum: Load;
  planRevisions: Readonly<Record<string, string>>;
  selectedPlanId: string | null;
  onSelectPlan: (planId: string | null) => void;
  planRevised: boolean;
  policies: Load | null;
  publicBaseUrl: string;
  onBack: () => void;
  onRefresh: () => void;
  onViewCourse: (courseId: string) => void;
  // R4b: the course draft for the selected plan, shown as given right after that plan's block (R4a spec 6.9);
  // nothing when no plan is selected or none is passed.
  draft?: ReactNode;
  // R4c: the selected plan's block, which goes with the draft; the page hands focus on when it goes with focus in it.
  planRef?: Ref<HTMLElement>;
  ref?: Ref<HTMLElement>;
}
// planRef comes out first: the React Compiler takes a prop named like a ref for one, and every later props.x for
// reading it during render.
function CurriculumBody({ planRef, ...props }: ProgramCurriculumProps) {
  const { curriculum, programId } = props;
  if (curriculum.status === 'loading')
    return <p role="status">正在加载课程表…</p>;
  if (curriculum.status === 'failed')
    return (
      <Line kind="warning">
        {curriculum.failure.status === 404
          ? '找不到这个培养方案，可能已经下线。'
          : `无法加载课程表。${apiErrorMessage(curriculum.failure)}`}
      </Line>
    );
  const parsed = parseCurriculum(curriculum.data, programId);
  if (parsed.kind === 'invalid')
    return <Line kind="warning">课程表的格式不对，没有显示。</Line>;
  const data = parsed.data;
  const { plans, notes } = availablePlans(data.plans, programId);
  const plan = plans.find((p) => p.plan_id === props.selectedPlanId);
  const revision =
    plan && Object.hasOwn(props.planRevisions, plan.plan_id)
      ? props.planRevisions[plan.plan_id]
      : undefined;
  const share =
    plan?.review_status === 'source_checked' && hash(revision)
      ? { ...plan, plan_content_sha256: revision }
      : null;
  return (
    <>
      <header data-kind="header" className={styles.header}>
        <h2 data-prefix>{oneLine(data.prefix)}</h2>
        <p data-name>{oneLine(data.full_name)}</p>
      </header>
      {data.notes && <Line kind="note">{collapseSpace(data.notes)}</Line>}
      {props.planRevised && (
        <Line kind="info">
          这个项目的版本化方案有更新，之前选的目录版本与路径已清除，请重新选择。
        </Line>
      )}
      {notes.map((n, i) => (
        <Line kind="note" key={i}>
          {n}
        </Line>
      ))}
      {plans.length === 0 ? (
        <Line kind="note">
          尚无可用版本化方案；旧课程表的校区、目录年度和路径未知。
        </Line>
      ) : (
        <div data-kind="select">
          <Select
            label={PLAN_LABEL}
            value={plan?.plan_id ?? '__none__'}
            onChange={(id) => props.onSelectPlan(id === '__none__' ? null : id)}
            options={[
              { value: '__none__', label: PLAN_PLACEHOLDER },
              ...plans.map((p) => ({ value: p.plan_id, label: scopeLabel(p) })),
            ]}
          />
        </div>
      )}
      {plan && (
        <section
          key={plan.plan_id}
          ref={planRef}
          className={styles.plan}
          aria-label="已选方案的版本化规则"
        >
          <h2 data-kind="note">
            {scopeLabel({
              ...plan,
              concentration:
                plan.concentration === null
                  ? null
                  : collapseSpace(plan.concentration),
            })}
          </h2>
          <Line kind="note">
            入学年份／Spring-Fall
            学期需另行确认；此处只展示规则，不判断注册或毕业资格。
          </Line>
          <Line kind="note">{`${plan.coverage === 'partial' ? '仅规则片段，不是完整培养方案' : '完整性由导入方声明，仍非个人资格审核'} · ${plan.review_status === 'source_checked' ? '来源片段已对照' : '尚未完成来源对照'}`}</Line>
          <Line>{plan.notes}</Line>
          <pre data-kind="text" className={styles.rules}>
            {programRuleLines(plan.requirements).join('\n')}
          </pre>
          <SourceLink href={plan.source_url}>官方目录来源</SourceLink>
          <Line kind="note">{`来源版次 ${plan.source_catalog_year} · 摘录日期 ${plan.captured_on} · 不证明当前班次开课`}</Line>
          {plan.source_html_sha256 !== null && (
            <Line>{`来源 HTML 字节摘要：${plan.source_html_sha256}（不证明来源真实或个人适用性）`}</Line>
          )}
          {plan.checked_by !== null && plan.checked_on !== null && (
            <Line>{`对照记录：${plan.checked_by} · ${plan.checked_on}`}</Line>
          )}
          <Disclosure title="来源摘录（非完整页面存档）">
            <Line>{plan.source_excerpt}</Line>
          </Disclosure>
          <ProgramPolicies
            plan={plan}
            revision={revision}
            policies={props.policies}
          />
        </section>
      )}
      {plan && props.draft}
      <Line kind="note">
        以下是旧课程表的课程分类与学期建议，未经官方核验；校区/年度/路径未知。
      </Line>
      <Disclosure title="分享这个培养方案">
        <Line kind="share_url">
          {shareUrl(props.publicBaseUrl, programId, share)}
        </Line>
        <Line kind="note">
          {share
            ? '链接定位已选方案的完整范围和当前内容版本；不是个人适用性或资格证明。'
            : '这里只分享项目入口，不携带方案年度／路径；对方仍需明确选择版本。'}
        </Line>
      </Disclosure>
      {data.semesters.length === 0 && (
        <Line kind="info">该培养方案还没有课程数据。</Line>
      )}
      {data.semesters.map((s, i) => (
        <section className={styles.semester} key={i}>
          <h2 data-kind="heading">{semesterHeading(s.semester)}</h2>
          {s.courses.map((c, j) => (
            <div key={j} className={styles.courseRow}>
              <div data-kind="course" className={styles.course}>
                <span data-code>
                  <CourseCode>{oneLine(c.primary_code)}</CourseCode>
                </span>
                <h3 data-name>{oneLine(c.primary_name)}</h3>
                <span
                  data-badge
                  className={`${styles.badge} ${['core', 'foundation', 'elective_pool', 'capstone'].includes(c.requirement_type) ? styles[c.requirement_type] : styles.foundation}`}
                >
                  {requirementLabel(c.requirement_type)}
                </span>
                {c.notes && <p data-notes>{oneLine(c.notes)}</p>}
              </div>
              <Button
                data-kind="button"
                data-course-id={c.course_id}
                aria-label={`查看 ${oneLine(c.primary_code)}`}
                onClick={() => props.onViewCourse(c.course_id)}
              >
                查看
              </Button>
            </div>
          ))}
        </section>
      ))}
    </>
  );
}
export function ProgramCurriculum({ ref, ...props }: ProgramCurriculumProps) {
  return (
    <section
      ref={ref}
      tabIndex={-1}
      className={styles.page}
      aria-label="项目课程表"
    >
      <Line kind="note">{PROGRAM_INTRO}</Line>
      <div className={styles.actions}>
        <Button
          data-kind="button"
          data-action="back"
          onClick={() => props.onBack()}
        >
          <ArrowLeft aria-hidden="true" />
          所有培养方案
        </Button>
        <Button
          data-kind="button"
          data-action="refresh"
          onClick={() => props.onRefresh()}
        >
          刷新方案及政策证据
        </Button>
      </div>
      <CurriculumBody {...props} />
    </section>
  );
}
