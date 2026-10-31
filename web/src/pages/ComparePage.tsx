import type { CSSProperties } from 'react';
import { useLayoutEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import type { ComparePageProps } from '../api/course';
import { Button } from '../components/Button';
import { CourseFactCell, CourseHeaderFacts } from '../components/CourseFacts';
import { EmptyState } from '../components/EmptyState';
import { resolveColumn, rowLabels } from '../models/compare';
import { coursePath } from '../models/coursePath';
import styles from './ComparePage.module.css';

export function ComparePage({
  ids,
  columns,
  onRemove,
  onClear,
  onReload,
}: ComparePageProps) {
  const selected = ids.slice(0, 4);
  const views = selected.map((id) => ({
    id,
    column: resolveColumn(columns[id]),
  }));
  const removeButtons = useRef(new Map<string, HTMLButtonElement>());
  const emptyAction = useRef<HTMLAnchorElement>(null);
  // 重新加载 goes as the columns it asks for load: focus goes to the table, which stays, without scrolling (R6).
  const table = useRef<HTMLDivElement>(null);
  const pendingFocus = useRef<{ id: string } | 'empty' | null>(null);
  useLayoutEffect(() => {
    const target = pendingFocus.current;
    if (target === null) return;
    pendingFocus.current = null;
    if (target === 'empty') emptyAction.current?.focus();
    else removeButtons.current.get(target.id)?.focus();
  }, [ids]);
  const tableStyle: CSSProperties & { '--columns': number } = {
    '--columns': selected.length,
  };
  return (
    <section className={styles.compare} aria-label="课程对比内容">
      <p className={styles.status}>
        已选择 {selected.length}/4
        门；按加入顺序展示，不排名、不判断选课或毕业资格。
      </p>
      <p className={styles.note}>
        列表只保存在这个页面会话里；刷新浏览器、登录或退出以后要重新加入。
      </p>
      {!selected.length ? (
        <EmptyState
          action={
            <Link ref={emptyAction} to="/">
              回到课程搜索
            </Link>
          }
        >
          在「课程搜索」页打开一门课的详情，点「加入对比」，最多选择 4 门课。
        </EmptyState>
      ) : (
        <>
          <div className={styles.controls}>
            <Button
              variant="ghost"
              onClick={() => {
                pendingFocus.current = 'empty';
                onClear();
              }}
            >
              清空对比
            </Button>
            {views.some((v) => v.column.status === 'error') && (
              <Button
                onClick={() => {
                  table.current?.focus({ preventScroll: true });
                  onReload();
                }}
              >
                重新加载
              </Button>
            )}
          </div>
          <div
            ref={table}
            className={styles.scroll}
            role="region"
            aria-label="课程对比表，可横向滚动"
            tabIndex={0}
          >
            <table className={styles.table} style={tableStyle}>
              <caption className="visually-hidden">
                按七项已记录信息比较所选课程，不排名或判断资格
              </caption>
              <thead>
                <tr>
                  <th scope="col">{selected.length} 门课</th>
                  {views.map(({ id, column }, index) => {
                    const name =
                      column.status === 'ready'
                        ? column.identity.primary_code
                        : id;
                    return (
                      <th scope="col" key={id}>
                        <div className={styles.columnHead}>
                          {column.status === 'ready' ? (
                            <CourseHeaderFacts body={column.body} />
                          ) : (
                            <p>
                              {column.status === 'loading'
                                ? '正在加载'
                                : `课程加载失败（${id}）：${column.message}`}
                            </p>
                          )}
                          <div className={styles.actions}>
                            {column.status === 'ready' && (
                              <Link
                                to={coursePath(column.identity.primary_code)}
                                state={{ courseId: id }}
                                aria-label={`查看 ${name}`}
                              >
                                查看
                              </Link>
                            )}
                            <Button
                              ref={(element) => {
                                if (element)
                                  removeButtons.current.set(id, element);
                                else removeButtons.current.delete(id);
                              }}
                              variant="ghost"
                              size="sm"
                              aria-label={`移出 ${name}`}
                              onClick={() => {
                                const neighbor =
                                  selected[index + 1] ?? selected[index - 1];
                                pendingFocus.current = neighbor
                                  ? { id: neighbor }
                                  : 'empty';
                                onRemove(id);
                              }}
                            >
                              移出
                            </Button>
                          </div>
                        </div>
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {rowLabels.map((row) => (
                  <tr key={row}>
                    <th scope="row">{row}</th>
                    {views.map(({ id, column }) => (
                      <td key={id}>
                        {column.status === 'ready' ? (
                          <CourseFactCell row={row} body={column.body} />
                        ) : column.status === 'loading' ? (
                          '正在加载'
                        ) : (
                          '加载失败'
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
