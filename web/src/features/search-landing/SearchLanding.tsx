import { Button } from '../../components/Button';
import { CourseCode } from '../../components/CourseCode';
import type { Load } from '../../api/load';
import { oneLine } from '../../models/courseDetailFormat';
import {
  coopLock,
  landingText,
  landingView,
  SAMPLE_QUESTIONS,
} from '../../models/landing';
import styles from './SearchLanding.module.css';

export interface SearchLandingProps {
  programs: Load;
  curricula: Readonly<Record<string, Load>>;
  coop: Load;
  onOpenProgram: (programId: string) => void;
  onViewCourse: (courseId: string) => void;
  onOpenCoop: () => void;
  onAsk: (query: string) => void;
  onRetry: () => void;
}
export function SearchLanding(props: SearchLandingProps) {
  const view = landingView(props.programs, props.curricula, props.coop);
  return (
    <section className={styles.landing} aria-label="搜索落地内容" data-landing>
      <h2 data-kind="title" className={styles.title}>
        问一门课，或者一个选课问题
      </h2>
      <div
        className={styles.discovery}
        aria-label="发现课程与经验"
        aria-busy={view.pending}
      >
        {view.programs.length > 0 && (
          <section className={styles.section}>
            <h3 data-kind="heading">按培养方案浏览</h3>
            <div className={styles.programs}>
              {view.programs.map((p) => (
                <Button
                  key={p.program_id}
                  data-kind="program"
                  data-program-id={p.program_id}
                  onClick={() => props.onOpenProgram(p.program_id)}
                >
                  {oneLine(p.prefix)} · {p.course_count} 门课
                </Button>
              ))}
            </div>
          </section>
        )}
        {view.starters.length > 0 && (
          <section className={styles.section}>
            <h3 data-kind="heading">入门推荐</h3>
            <div className={styles.starters}>
              {view.starters.map(({ programId, prefix, course }) => (
                <div key={programId} className={styles.card}>
                  <div data-kind="starter" className={styles.starter}>
                    <span data-code>
                      <CourseCode>
                        {landingText(course.primary_code)}
                      </CourseCode>
                    </span>
                    <span data-prefix className={styles.pill}>
                      {landingText(prefix)}
                    </span>
                    <p data-name>{landingText(course.primary_name)}</p>
                  </div>
                  <Button
                    size="sm"
                    data-kind="view"
                    data-course-id={course.course_id}
                    aria-label={`查看 ${oneLine(course.primary_code)}`}
                    onClick={() => props.onViewCourse(course.course_id)}
                  >
                    查看
                  </Button>
                </div>
              ))}
            </div>
          </section>
        )}
        {view.coop.length > 0 && (
          <section className={styles.section}>
            <h3 data-kind="heading">最近的 Co-op 经验</h3>
            <ul className={styles.coop}>
              {view.coop.map((row, i) => {
                const lock = coopLock(row);
                return (
                  <li key={i}>
                    <p data-kind="coop" className={styles.plain}>
                      <strong data-company>{landingText(row.company)}</strong> ·{' '}
                      <span data-role>{landingText(row.role)}</span>
                    </p>
                    {lock && (
                      <p data-kind="lock" className={styles.note}>
                        这条有{lock}：你分享的经验公开后解锁
                      </p>
                    )}
                  </li>
                );
              })}
            </ul>
            <Button data-kind="coop_link" onClick={props.onOpenCoop}>
              去看看
            </Button>
          </section>
        )}
        {view.pending && (
          <p role="status" className={styles.note}>
            正在加载推荐内容…
          </p>
        )}
        {view.transient && (
          <div className={styles.retry}>
            <p data-kind="notice" className={styles.note}>
              部分内容暂时没加载出来。
            </p>
            <Button
              data-kind="button"
              data-action="retry"
              onClick={props.onRetry}
            >
              重新加载
            </Button>
          </div>
        )}
      </div>
      <section className={styles.section}>
        <h3 data-kind="heading">试试这样问</h3>
        <div className={styles.samples}>
          {SAMPLE_QUESTIONS.map((q) => (
            <Button
              key={q.query}
              data-kind="sample"
              data-query={q.query}
              onClick={() => props.onAsk(q.query)}
            >
              {q.label}
            </Button>
          ))}
        </div>
        <p data-kind="note" className={styles.note}>
          也可以直接用一句话问，比如「工作量最轻的 3 学分 ML
          课」或「讲反向传播的课」。
        </p>
      </section>
    </section>
  );
}
