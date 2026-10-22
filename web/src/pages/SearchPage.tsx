import { Info, Plus } from 'lucide-react';
import type { ReactNode } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { Button } from '../components/Button';
import { CourseCode } from '../components/CourseCode';
import { DataNote } from '../components/DataNote';
import { IconButton } from '../components/IconButton';
import { Select } from '../components/Select';
import {
  answerCodes,
  coursePath,
  exampleQuestions,
  findCourse,
  planOptions,
  projectOptions,
} from '../fixtures/courses';
import { usePrototype } from '../layout/PrototypeContext';
import styles from './SearchPage.module.css';

function Conversation() {
  const state = usePrototype();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const empty = params.get('demo') === 'empty' && !state.hasSubmitted;
  return (
    <section className={styles.chat} aria-label="课程问答">
      <div className={styles.context}>
        <Select
          label="项目"
          value={state.project}
          onChange={state.setProject}
          options={projectOptions}
        />
        <Select
          label="方案"
          value={state.plan}
          onChange={state.setPlan}
          options={planOptions}
          disabled={state.project === 'none'}
        />
        <span className={styles.hint}>
          <Info aria-hidden="true" />
          选了以后按方案解释规则，不判断资格
        </span>
      </div>
      {empty ? (
        <div className={styles.welcome}>
          <h2>问一门课，或者一个选课问题</h2>
          <p>课程信息来自 NEU 课程目录的存档（2026–2027），6,469 门课。</p>
          <div className={styles.examples}>
            {exampleQuestions.map((question) => (
              <Button key={question} onClick={() => state.submit(question)}>
                {question}
              </Button>
            ))}
          </div>
          <p>
            游客也能搜课、看培养方案；左上角菜单里有培养方案、Co-op 和对比。
          </p>
        </div>
      ) : (
        <>
          <p className={styles.question} aria-label="演示问题">
            {state.question}
          </p>
          <article className={styles.answer} aria-label="示例回答">
            <p>按 2026–2027 目录，课名就是机器学习的有两门：</p>
            <ul>
              <li>
                <CourseCode>CS 6140</CourseCode> Machine Learning：先修是 CS
                5800 或 CS 7800，最低 C-，所以一般先修完 CS 5800 再选。
              </li>
              <li>
                <CourseCode>DS 5220</CourseCode> Supervised Machine Learning and
                Learning Theory：目录没有列先修，偏理论。
              </li>
            </ul>
            <p>
              想先打基础，<CourseCode>CS 5100</CourseCode> Foundations of
              Artificial Intelligence 也讲到机器学习入门，目录同样没有列先修。
            </p>
            <footer className={styles.answerFooter}>
              <span>
                依据：4 门课的目录存档 ·{' '}
                {state.plan === 'none'
                  ? '没选方案，所以没判断能不能计入'
                  : '按所选方案演示，不判断资格'}
              </span>
            </footer>
            <DataNote>
              <ul>
                <li>
                  这是固定示例回答，不是真实问答结果；输入仅更新本地演示问题。
                </li>
                <li>
                  简介和先修来自目录存档示例，不是实时核对；没有列出不代表没有要求。
                </li>
                <li>本原型不判断个人适用年度、能否注册或毕业资格。</li>
              </ul>
            </DataNote>
          </article>
          <div className={styles.follow} aria-label="接着问">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => state.submit('CS 6140 作业量大吗？')}
            >
              CS 6140 作业量大吗？
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => state.submit('CS 5800 讲什么？')}
            >
              CS 5800 讲什么？
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                void navigate('/compare');
              }}
            >
              对比这几门
            </Button>
          </div>
        </>
      )}
    </section>
  );
}

function AnswerCourses() {
  const state = usePrototype();
  const [params] = useSearchParams();
  if (params.get('demo') === 'empty' && !state.hasSubmitted) return null;
  return (
    <section className={styles.panel} aria-labelledby="answer-courses-title">
      <div className={styles.panelHeading}>
        <h2 id="answer-courses-title">回答用到的课</h2>
        <span>4 门</span>
      </div>
      <div className={styles.results}>
        {answerCodes.map((code) => {
          const course = findCourse(code);
          if (!course) return null;
          return (
            <div className={styles.courseRow} key={code}>
              <CourseCode>{code}</CourseCode>
              <div>
                <strong lang="en">{course.title}</strong>
                <p className={styles.meta}>
                  {course.credits} 学分 ·{' '}
                  {course.prerequisite
                    ? '先修 CS 5800 或 CS 7800（C-）'
                    : '目录没有列先修'}
                  {code === 'CS 5800' ? ' · CS 6140 的先修' : ''}
                </p>
              </div>
              <div className={styles.actions}>
                <Link
                  className={styles.view}
                  to={coursePath(code)}
                  aria-label={`查看 ${code}`}
                >
                  查看
                </Link>
                <IconButton
                  size="sm"
                  aria-label={`加入对比 ${code}`}
                  variant="ghost"
                  onClick={() => {
                    console.info('prototype.compare', code);
                    state.announce(
                      `已记录 ${code} 的演示操作；R1 不向对比列表添加数据。`,
                    );
                  }}
                >
                  <Plus aria-hidden="true" />
                </IconButton>
              </div>
            </div>
          );
        })}
      </div>
      <p className={styles.tip}>
        点「查看」在这里打开课程详情；点 + 加入对比，最多 4 门。
      </p>
    </section>
  );
}

export function SearchWorkspace({ detail }: { detail?: ReactNode }) {
  const [params] = useSearchParams();
  const state = usePrototype();
  const empty = params.get('demo') === 'empty' && !state.hasSubmitted;
  return (
    <>
      <p className={`${styles.guest} ${empty ? styles.emptyGuest : ''}`}>
        <Info aria-hidden="true" />
        <span>
          游客也能搜课、看培养方案。登录并分享一条 Co-op
          经验以后，能看到面试细节。<Link to="/coop">规则</Link>
        </span>
      </p>
      <div
        className={`${styles.columns} ${detail ? styles.detailOpen : ''} ${empty ? styles.emptyColumns : ''}`}
      >
        <Conversation />
        {detail ?? <AnswerCourses />}
      </div>
    </>
  );
}

export function SearchPage() {
  return <SearchWorkspace />;
}
