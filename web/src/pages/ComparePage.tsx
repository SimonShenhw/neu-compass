import { Check } from 'lucide-react';
import type { CSSProperties, ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { Button } from '../components/Button';
import { Chips } from '../components/Chips';
import { CourseCode } from '../components/CourseCode';
import { EmptyState } from '../components/EmptyState';
import { Select } from '../components/Select';
import { Toggle } from '../components/Toggle';
import { coursePath, findCourse, planOptions } from '../fixtures/courses';
import type { Course } from '../fixtures/courses';
import { usePrototype } from '../layout/PrototypeContext';
import { useLayoutEffect, useRef, useState } from 'react';
import styles from './ComparePage.module.css';

export function ComparePage() {
  const state = usePrototype();
  const [onlyDifferent, setOnlyDifferent] = useState(true);
  const removeButtons = useRef(new Map<string, HTMLButtonElement>());
  const emptyAction = useRef<HTMLAnchorElement>(null);
  const pendingFocus = useRef<{ code: string } | 'empty' | null>(null);
  const selected = state.comparison
    .map(findCourse)
    .filter((course): course is Course => course !== undefined);
  useLayoutEffect(() => {
    const target = pendingFocus.current;
    if (target === null) return;
    pendingFocus.current = null;
    if (target === 'empty') emptyAction.current?.focus();
    else removeButtons.current.get(target.code)?.focus();
  }, [state.comparison]);
  if (!selected.length)
    return (
      <EmptyState
        action={
          <Link ref={emptyAction} to="/">
            回到课程搜索
          </Link>
        }
      >
        对比列表为空。在课程搜索页打开课程详情，最多选择 4 门课。
      </EmptyState>
    );
  const rows: {
    label: string;
    key: (course: Course) => string;
    cell: (course: Course) => ReactNode;
  }[] = [
    {
      label: '学分',
      key: (course) => String(course.credits),
      cell: (course) => `${course.credits} 学分`,
    },
    {
      label: '目录年份',
      key: (course) => course.year,
      cell: (course) => course.year,
    },
    {
      label: '先修',
      key: (course) => course.prerequisiteText,
      cell: (course) =>
        course.prerequisite ? (
          <strong>{course.prerequisiteText}</strong>
        ) : (
          course.prerequisiteText
        ),
    },
    {
      label: '学生评价（估计）',
      key: (course) => course.review,
      cell: (course) => course.review,
    },
    {
      label: '讲什么',
      key: (course) => course.description,
      cell: (course) => (
        <p lang="en" className={styles.clamp}>
          {course.description}
        </p>
      ),
    },
    {
      label: '主题',
      key: (course) => (course.comparisonTopics ?? course.topics).join('|'),
      cell: (course) => (
        <Chips items={course.comparisonTopics ?? course.topics} />
      ),
    },
  ];
  const visibleRows = rows.filter(
    (row) => !onlyDifferent || new Set(selected.map(row.key)).size > 1,
  );
  const tableStyle: CSSProperties & { '--columns': number } = {
    '--columns': selected.length,
  };
  return (
    <section className={styles.compare} aria-label="课程对比内容">
      <div className={styles.controls}>
        <Select
          label="按方案看"
          value={state.plan}
          onChange={state.setPlan}
          options={planOptions}
        />
        <Toggle
          checked={onlyDifferent}
          onChange={setOnlyDifferent}
          label="只看不同的行"
        />
        <Button
          size="sm"
          variant="ghost"
          onClick={() => {
            pendingFocus.current = 'empty';
            state.clear();
          }}
        >
          清空对比
        </Button>
        <span className={styles.count}>
          已选 {selected.length} / 4 门 · 按加入的顺序
        </span>
      </div>
      {onlyDifferent && (
        <p className={styles.same}>
          <Check aria-hidden="true" />这 {selected.length} 门都是 4 学分，都在
          2026–2027 目录里。
        </p>
      )}
      <div
        className={styles.scroll}
        role="region"
        aria-label="课程对比表，可横向滚动"
        tabIndex={0}
      >
        <table className={styles.table} style={tableStyle}>
          <caption className="visually-hidden">
            按字段比较所选课程；本表使用固定演示数据
          </caption>
          <thead>
            <tr>
              <th scope="col">{selected.length} 门课</th>
              {selected.map((course, index) => (
                <th scope="col" key={course.code}>
                  <div className={styles.columnHead}>
                    <span>
                      <CourseCode>{course.code}</CourseCode>
                    </span>
                    <strong lang="en">{course.title}</strong>
                    <div className={styles.actions}>
                      <Link
                        to={coursePath(course.code)}
                        aria-label={`查看 ${course.code}`}
                      >
                        查看
                      </Link>
                      <Button
                        ref={(element) => {
                          if (element)
                            removeButtons.current.set(course.code, element);
                          else removeButtons.current.delete(course.code);
                        }}
                        variant="ghost"
                        size="sm"
                        aria-label={`移出 ${course.code}`}
                        onClick={() => {
                          const neighbor =
                            selected[index + 1] ?? selected[index - 1];
                          pendingFocus.current = neighbor
                            ? { code: neighbor.code }
                            : 'empty';
                          state.remove(course.code);
                        }}
                      >
                        移出
                      </Button>
                    </div>
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visibleRows.map((row) => (
              <tr key={row.label}>
                <th scope="row">{row.label}</th>
                {selected.map((course) => (
                  <td key={course.code}>{row.cell(course)}</td>
                ))}
              </tr>
            ))}
            <tr>
              <th scope="row">在你的方案里</th>
              <td colSpan={selected.length} className={styles.note}>
                {state.plan === 'none'
                  ? '选了方案以后，这一行显示每门课在哪一组。'
                  : '已选择方案；R1 尚未接入规则，课程位置仍未知。'}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p className={styles.note}>
        对比列表只保存在这次会话里；刷新浏览器、登录或登出以后要重新加入。「讲什么」只显示开头几行，点「查看」看全文。
      </p>
      <p className={styles.note}>
        R1 预填四门假数据以便验收，刷新会恢复示例；不模拟真实会话或资格判断。
      </p>
    </section>
  );
}
