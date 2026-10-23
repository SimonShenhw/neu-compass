import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { CourseCode } from '../components/CourseCode';
import { CourseRequisites } from '../features/requisites/CourseRequisites';
import {
  requisitesFixture,
  requisitesFixtures,
} from '../fixtures/requisitesDemo';
import type { RequisitesFixture } from '../fixtures/requisitesDemo';
import styles from '../features/requisites/Requisites.module.css';

function DemoSession({ fixture }: { fixture: RequisitesFixture }) {
  const [notice, setNotice] = useState('');
  return (
    <div className={styles.session}>
      <p>{fixture.notes}</p>
      <h2>
        <CourseCode>{fixture.body.primary_code}</CourseCode>
        {fixture.body.primary_name}
      </h2>
      <CourseRequisites
        key={fixture.body.course_id}
        course={fixture.body}
        requisites={fixture.body.course_requisites}
        prerequisites={fixture.body.prerequisites}
        onOpenCourse={(code) => setNotice(`演示：这里会打开 ${code}`)}
      />
      <p role="status" aria-label="课程导航演示结果">
        {notice}
      </p>
    </div>
  );
}
export function RequisitesDemoPage() {
  const [params, setParams] = useSearchParams();
  const fixture = requisitesFixture(params.get('case'));
  return (
    <div className={styles.session}>
      <section className={styles.demo} aria-label="先修要求演示设置">
        <label>
          演示数据
          <select
            value={fixture.case}
            onChange={(event) => {
              const next = new URLSearchParams(params);
              next.set('case', event.target.value);
              void setParams(next, { replace: true });
            }}
          >
            {requisitesFixtures.map((item) => (
              <option key={item.case} value={item.case}>
                {item.case}
              </option>
            ))}
          </select>
        </label>
      </section>
      <DemoSession key={fixture.case} fixture={fixture} />
    </div>
  );
}
