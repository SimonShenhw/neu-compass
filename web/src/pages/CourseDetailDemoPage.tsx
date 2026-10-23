import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { CourseDetail } from '../features/course-detail/CourseDetail';
import {
  courseDetailFixture,
  courseDetailFixtures,
  detailCompareChoice,
  detailCompareIds,
  detailCompareOptions,
} from '../fixtures/courseDetailDemo';
import type {
  CourseDetailFixture,
  DetailCompareChoice,
} from '../fixtures/courseDetailDemo';
import styles from '../features/course-detail/CourseDetail.module.css';

function DetailDemoSession({
  fixture,
  choice,
}: {
  fixture: CourseDetailFixture;
  choice: DetailCompareChoice;
}) {
  const [notice, setNotice] = useState('');
  return (
    <>
      <p>{fixture.notes}</p>
      <CourseDetail
        course={fixture.body}
        compare={detailCompareIds(choice, fixture.body.course_id)}
        onAddToCompare={(id) => setNotice(`演示：这里会把 ${id} 加入对比`)}
        onOpenCourse={(code) => setNotice(`演示：这里会打开 ${code}`)}
      />
      <p role="status" aria-label="课程详情演示结果">
        {notice}
      </p>
    </>
  );
}
export function CourseDetailDemoPage() {
  const [params, setParams] = useSearchParams();
  const fixture = courseDetailFixture(params.get('case')),
    choice = detailCompareChoice(params.get('compare'));
  function change(name: string, value: string) {
    const next = new URLSearchParams(params);
    next.set(name, value);
    void setParams(next, { replace: true });
  }
  return (
    <div className={styles.session}>
      <section className={styles.demo} aria-label="课程详情演示设置">
        <label>
          演示数据
          <select
            value={fixture.case}
            onChange={(event) => change('case', event.target.value)}
          >
            {courseDetailFixtures.map((item) => (
              <option key={item.case} value={item.case}>
                {item.case}
              </option>
            ))}
          </select>
        </label>
        <label>
          对比列表
          <select
            value={choice}
            onChange={(event) => change('compare', event.target.value)}
          >
            {detailCompareOptions.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
      </section>
      <DetailDemoSession
        key={`${fixture.case}:${choice}`}
        fixture={fixture}
        choice={choice}
      />
    </div>
  );
}
