import type { Ref } from 'react';
import type { Load } from '../../api/load';
import { Button } from '../../components/Button';
import { parseProgramList } from '../../models/programs';
import { oneLine } from '../../models/courseDetailFormat';
import { apiErrorMessage, PROGRAM_INTRO } from '../../models/programFormat';
import { Line } from './ProgramParts';
import styles from './Programs.module.css';

export interface ProgramListProps {
  programs: Load;
  onOpenProgram: (programId: string) => void;
  onRetry: () => void;
  ref?: Ref<HTMLElement>;
}
export function ProgramList({
  programs,
  onOpenProgram,
  onRetry,
  ref,
}: ProgramListProps) {
  const parsed =
    programs.status === 'ready' ? parseProgramList(programs.data) : null;
  return (
    <section
      ref={ref}
      tabIndex={-1}
      className={styles.page}
      aria-label="培养方案列表"
    >
      <Line kind="note">{PROGRAM_INTRO}</Line>
      {programs.status === 'loading' && <p role="status">正在加载培养方案…</p>}
      {programs.status === 'failed' && (
        <>
          <Line kind="warning">{`无法加载培养方案列表。${apiErrorMessage(programs.failure)}`}</Line>
          <Button
            data-kind="button"
            data-action="retry"
            onClick={() => onRetry()}
          >
            重新加载
          </Button>
        </>
      )}
      {parsed?.kind === 'invalid' && (
        <Line kind="warning">培养方案列表的格式不对，没有显示。</Line>
      )}
      {parsed?.kind === 'ok' &&
        (parsed.data.length === 0 ? (
          <Line kind="info">暂时还没有可浏览的培养方案。</Line>
        ) : (
          <div className={styles.cards}>
            {parsed.data.map((p) => (
              <article key={p.program_id} className={styles.card}>
                <div data-kind="program_card">
                  <h2 data-prefix>{oneLine(p.prefix)}</h2>
                  <p data-name>{oneLine(p.full_name)}</p>
                  <span data-count className={styles.badge}>
                    {p.course_count} 门课程
                  </span>
                </div>
                <Line kind="note">{`旧课程表标签未核验 · 可用版本化规则 ${p.plan_count} 份`}</Line>
                <Button
                  data-kind="button"
                  data-program-id={p.program_id}
                  aria-label={`查看 ${oneLine(p.prefix)} 的课程表`}
                  onClick={() => onOpenProgram(p.program_id)}
                >
                  查看课程表
                </Button>
              </article>
            ))}
          </div>
        ))}
    </section>
  );
}
