import { ArrowLeft, Plus, Share2 } from 'lucide-react';
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Button } from '../components/Button';
import { Chips } from '../components/Chips';
import { CourseCode } from '../components/CourseCode';
import { DataNote } from '../components/DataNote';
import { EmptyState } from '../components/EmptyState';
import { RequisiteTree } from '../components/RequisiteTree';
import { codeFromPath, coursePath, findCourse } from '../fixtures/courses';
import { usePrototype } from '../layout/PrototypeContext';
import { SearchWorkspace } from './SearchPage';
import styles from './CourseDetail.module.css';

function DetailPanel({ code }: { code: string }) {
  const course = findCourse(code);
  const [expanded, setExpanded] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);
  const navigate = useNavigate();
  const state = usePrototype();
  if (!course)
    return (
      <EmptyState action={<Link to="/">返回首页</Link>}>
        找不到这门演示课程：{code}
      </EmptyState>
    );
  return (
    <section className={styles.detail} aria-label={`${code} 课程详情`}>
      <Link to="/" className={styles.back}>
        <ArrowLeft aria-hidden="true" />
        回答用到的课
      </Link>
      <header className={styles.header}>
        <span>
          <CourseCode size="lg">{code}</CourseCode>
        </span>
        <h2 lang="en">{course.title}</h2>
        <p className={styles.facts}>
          {course.credits} 学分 · 目录 {course.year}
        </p>
        <div className={styles.actions}>
          <Button
            variant="primary"
            onClick={() => {
              console.info('prototype.compare', code);
              state.announce(
                `已记录 ${code} 的演示操作；R1 不向对比列表添加数据。`,
              );
            }}
          >
            <Plus aria-hidden="true" />
            加入对比
          </Button>
          <Button
            variant="ghost"
            onClick={() => setShareOpen((previous) => !previous)}
            aria-expanded={shareOpen}
          >
            <Share2 aria-hidden="true" />
            分享
          </Button>
        </div>
        {shareOpen && (
          <p className={styles.share}>
            演示路径：<Link to={coursePath(code)}>{coursePath(code)}</Link>
            （本地原型，未发布）
          </p>
        )}
      </header>
      <section className={styles.section} aria-labelledby="description-title">
        <h3 id="description-title">讲什么</h3>
        <p lang="en">{course.description}</p>
        <p id="full-description" lang="en" hidden={!expanded}>
          {course.fullDescription}
        </p>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => setExpanded((previous) => !previous)}
          aria-expanded={expanded}
          aria-controls="full-description"
        >
          {expanded ? '收起全文' : '展开全文'}
        </Button>
        <Chips items={course.topics} />
      </section>
      <section className={styles.section} aria-labelledby="prerequisite-title">
        <h3 id="prerequisite-title">
          先修 <small>{course.year} 目录</small>
        </h3>
        {course.prerequisite ? (
          <RequisiteTree
            node={course.prerequisite}
            onOpen={(value) => {
              void navigate(coursePath(value));
            }}
          />
        ) : (
          <EmptyState>
            {course.prerequisiteText}；不代表已证明没有要求。
          </EmptyState>
        )}
        <p className={styles.muted}>
          同修：本原型未建模；未列出或未解析的要求仍未知。
        </p>
      </section>
      <section className={styles.section}>
        <h3>在你的培养方案里</h3>
        <EmptyState>
          {state.plan === 'none'
            ? '还没选方案。在左边选了项目和方案以后，这里会写 ' +
              code +
              ' 在哪一组。'
            : '已选择方案；R1 尚未接入规则，课程位置仍未知。'}
        </EmptyState>
      </section>
      <section className={styles.section}>
        <h3>学生评价（估计）</h3>
        <EmptyState>这门课还没有足够的评价数据。</EmptyState>
      </section>
      <DataNote>
        <ul>
          <li>本页只用固定假数据演示布局；未连接真实课程接口。</li>
          <li>
            简介和先修来自 NEU
            官方课程目录的存档副本示例，不是实时核对；抓取日期没有记录。
          </li>
          <li>学生评价的工作量、难度是根据公开评价的估计，不是官方信息。</li>
          <li>
            先修按目录原文整理，不判断你能不能注册；能否选课以学校系统为准。
          </li>
        </ul>
      </DataNote>
    </section>
  );
}

export function CourseDetail() {
  const { code = '' } = useParams();
  const normalized = codeFromPath(code);
  return (
    <SearchWorkspace
      detail={<DetailPanel key={normalized} code={normalized} />}
    />
  );
}
