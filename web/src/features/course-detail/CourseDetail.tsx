import { Button } from '../../components/Button';
import { CourseCode } from '../../components/CourseCode';
import { CourseRequisites } from '../requisites/CourseRequisites';
import { parseCourseDetail } from '../../models/courseDetail';
import type { DetailView } from '../../models/courseDetail';
import { MAX_COMPARE_COURSES } from '../../models/compareList';
import { oneLine, percentEven, pyG } from '../../models/courseDetailFormat';
import { DetailEvidence, DetailOverview } from './DetailEvidence';
import { DetailDisclosure, DetailLine, DetailText } from './DetailPrimitives';
import styles from './CourseDetail.module.css';

export interface CourseDetailProps {
  course: unknown;
  compare: readonly string[];
  onAddToCompare: (courseId: string) => void;
  onOpenCourse: (code: string) => void;
}
export const INVALID_DETAIL = '课程详情的格式不对，没有显示。';
const badges = new Map([
  ['core', '核心 · core'],
  ['foundation', '基础 · foundation'],
  ['elective_pool', '选修池 · elective'],
  ['capstone', '毕业项目 · capstone'],
]);
export function CourseDetail({
  course,
  compare,
  onAddToCompare,
  onOpenCourse,
}: CourseDetailProps) {
  const parsed = parseCourseDetail(course);
  if (parsed.kind === 'invalid')
    return <DetailText kind="warning">{INVALID_DETAIL}</DetailText>;
  const b = parsed.body,
    already = compare.includes(b.course_id),
    full = compare.length >= MAX_COMPARE_COURSES;
  const estimates: string[] = [];
  if (b.workload_hours_per_week !== null)
    estimates.push(`每周约 ${pyG(b.workload_hours_per_week)} 小时`);
  if (b.difficulty_score !== null)
    estimates.push(`难度 ${pyG(b.difficulty_score)}/5`);
  return (
    <section aria-label="课程详情" className={styles.detail} data-course-detail>
      <DetailHeader body={b} />
      <div className={styles.compare}>
        <Button
          variant="primary"
          data-kind="button"
          disabled={already || full}
          onClick={() => onAddToCompare(b.course_id)}
        >
          加入对比
        </Button>
        {already ? (
          <DetailText kind="note">{`已在对比中（${compare.length}/${MAX_COMPARE_COURSES}）`}</DetailText>
        ) : full ? (
          <DetailText kind="note">
            对比列表已满，请到课程对比页先移出一门。
          </DetailText>
        ) : null}
      </div>
      <DetailOverview evidence={b.answer_evidence} />
      {estimates.length > 0 && (
        <DetailLine label="学生评价里的估计" value={estimates.join(' · ')} />
      )}
      <div data-kind="requisites_panel">
        <CourseRequisites
          key={b.course_id}
          course={{
            course_id: b.course_id,
            primary_code: b.primary_code,
            primary_name: b.primary_name,
          }}
          requisites={b.course_requisites}
          prerequisites={b.prerequisites}
          onOpenCourse={onOpenCourse}
        />
      </div>
      {b.grading_components.length > 0 && (
        <DetailLine
          label="考核构成"
          value={b.grading_components
            .map((g) =>
              g.weight === null
                ? g.name
                : `${g.name} ${percentEven(g.weight)}%`,
            )
            .join(' · ')}
        />
      )}
      {b.topics_covered.length > 0 && (
        <>
          <DetailText kind="heading">主题</DetailText>
          <DetailPills items={b.topics_covered} />
        </>
      )}
      {b.skill_tags.length > 0 && (
        <>
          <DetailText kind="heading">技能</DetailText>
          <DetailPills items={b.skill_tags} />
        </>
      )}
      {b.career_relevance.length > 0 && (
        <DetailLine label="职业方向" value={b.career_relevance.join(' · ')} />
      )}
      {b.professor.length > 0 && (
        <DetailLine label="任课老师" value={b.professor.join(', ')} />
      )}
      {b.program_context.length > 0 && (
        <>
          <DetailText kind="heading">在培养方案里的位置</DetailText>
          {b.program_context.map((p, index) => (
            <div key={index} data-kind="program_row" className={styles.program}>
              <strong data-program-name>{oneLine(p.program_name)}</strong>
              <span className={styles.pill} data-badge>
                {badges.get(p.requirement_type) ?? '基础 · foundation'}
              </span>
              {p.semester_recommended !== null && (
                <span
                  className={styles.pill}
                  data-semester
                >{`第 ${p.semester_recommended} 学期推荐`}</span>
              )}
            </div>
          ))}
        </>
      )}
      {b.ai_policy && (
        <DetailDisclosure label="AI 使用政策">
          {b.ai_policy.permitted_tools.length > 0 && (
            <DetailLine
              label="允许"
              value={b.ai_policy.permitted_tools.join(', ')}
            />
          )}
          {b.ai_policy.banned_tools.length > 0 && (
            <DetailLine
              label="禁止"
              value={b.ai_policy.banned_tools.join(', ')}
            />
          )}
          {b.ai_policy.disclosure_required && (
            <DetailText>使用 AI 需要声明</DetailText>
          )}
          {b.ai_policy.notes && (
            <DetailText>{b.ai_policy.notes.replaceAll('\r', '')}</DetailText>
          )}
        </DetailDisclosure>
      )}
      <DetailEvidence body={b} />
    </section>
  );
}
function DetailHeader({ body }: { body: DetailView }) {
  const chips: { label: string; value: string }[] = [];
  if (body.term) chips.push({ label: 'Term', value: oneLine(body.term) });
  if (body.credits !== null)
    chips.push({ label: 'Credits', value: String(body.credits) });
  if (body.delivery_mode)
    chips.push({
      label: 'Mode',
      value: oneLine(body.delivery_mode.replaceAll('_', ' ')),
    });
  return (
    <header data-kind="header" className={styles.header}>
      <span data-code className={styles.code}>
        <CourseCode size="lg">{oneLine(body.primary_code)}</CourseCode>
      </span>
      <h2 data-name>{oneLine(body.primary_name)}</h2>
      {chips.length > 0 && (
        <div className={styles.metadata}>
          {chips.map((chip) => (
            <div key={chip.label} data-chip>
              <span data-chip-label>{chip.label}</span>
              <strong data-chip-value>{chip.value}</strong>
            </div>
          ))}
        </div>
      )}
    </header>
  );
}
function DetailPills({ items }: { items: string[] }) {
  return (
    <div data-kind="pills" className={styles.pills}>
      {items.map((item, index) => (
        <span key={index} className={styles.pill}>
          {oneLine(item)}
        </span>
      ))}
    </div>
  );
}
