import { Building2, ChevronDown, LockKeyhole } from 'lucide-react';
import { useId } from 'react';
import { Link } from 'react-router-dom';
import { CourseCode } from './CourseCode';
import { industryName } from '../models/coop';
import type { CoopRecord } from '../models/coop';
import styles from './CoopCard.module.css';

const contentLabels = { 0: '基础信息', 1: '含面试细节', 2: '含薪资区间' };

export function CoopCard({ record }: { record: CoopRecord }) {
  const titleId = useId();
  const hasInterview = Boolean(
    record.interview_summary || record.technical_questions,
  );
  return (
    <article className={styles.card} aria-labelledby={titleId}>
      <header className={styles.header}>
        <span className={styles.mark}>
          <Building2 aria-hidden="true" />
        </span>
        <div className={styles.identity}>
          <h3 id={titleId}>
            {record.company} — {record.role}
            {record.coop_term ? ` · ${record.coop_term}` : ''}
          </h3>
        </div>
        <span className={styles.level} title="记录包含的字段，不是查看者权限">
          {contentLabels[record.visibility_level]}
        </span>
      </header>
      <dl className={styles.metadata}>
        {record.industry && (
          <div>
            <dt>行业</dt>
            <dd>{industryName(record.industry)}</dd>
          </div>
        )}
        {record.duration_months !== null && (
          <div>
            <dt>时长</dt>
            <dd>{record.duration_months} 个月</dd>
          </div>
        )}
      </dl>
      {record.related_courses.length > 0 && (
        <div className={styles.courses}>
          <span>相关课程</span>
          {record.related_courses.map((code) => (
            <Link
              key={code}
              to={`/course/${encodeURIComponent(code.replaceAll(' ', '-'))}`}
            >
              <CourseCode>{code}</CourseCode>
            </Link>
          ))}
        </div>
      )}
      {record.interview_summary && (
        <details className={styles.detail}>
          <summary>
            面试经过
            <ChevronDown aria-hidden="true" />
          </summary>
          <p>{record.interview_summary}</p>
        </details>
      )}
      {record.technical_questions && (
        <details className={styles.detail}>
          <summary>
            技术问题
            <ChevronDown aria-hidden="true" />
          </summary>
          <p>{record.technical_questions}</p>
        </details>
      )}
      {record.visibility_level === 1 && !hasInterview && (
        <p className={styles.locked}>
          <LockKeyhole aria-hidden="true" />
          <span>这条有面试细节：你分享的经验有 1 条公开后解锁</span>
        </p>
      )}
      {record.salary_range_usd ? (
        <div className={styles.salary}>
          <span>薪资区间</span>
          <strong>{record.salary_range_usd}</strong>
        </div>
      ) : record.visibility_level === 2 ? (
        <p className={styles.locked}>
          <LockKeyhole aria-hidden="true" />
          <span>这条有薪资区间：你分享的经验有 2 条公开后解锁</span>
        </p>
      ) : null}
    </article>
  );
}
