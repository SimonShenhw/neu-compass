import { isTransient } from '../api/load';
import type { Load } from '../api/load';
import type { ProgramCurriculum } from '../api/programs';
import type { Turn } from './chatTurn';
import { parseProgramList, parseCurriculum } from './programs';
import { parseCoopPreview } from './coopPreview';
import type { CoopPreview } from './coopPreview';

export const FEATURED_PROGRAM_IDS = ['aai-ms', 'cs-ms', 'ds-ms'] as const;
export const SAMPLE_QUESTIONS = [
  { label: 'CS 5800', query: 'CS 5800' },
  { label: '适合入门的 AI 选修课', query: 'easy AI elective for ML beginner' },
  { label: '数据库方向的课', query: 'database management systems' },
  { label: '课业最轻的 ML 课', query: 'lightest workload ML class' },
] as const;
export const showLanding = (turns: readonly Turn[]) => turns.length === 0;
export function semester1Pick(
  curriculum: Pick<ProgramCurriculum, 'semesters'>,
) {
  for (const group of curriculum.semesters) {
    if (group.semester !== 1) continue;
    const pick = group.courses.find(
      (c) =>
        c.requirement_type === 'core' || c.requirement_type === 'foundation',
    );
    if (pick) return pick;
  }
  return null;
}
export function coopLock(row: CoopPreview): '面试细节' | '薪资区间' | null {
  if (
    row.visibility_level === 1 &&
    !row.interview_summary &&
    !row.technical_questions
  )
    return '面试细节';
  if (row.visibility_level === 2 && !row.salary_range_usd) return '薪资区间';
  return null;
}
export const landingText = (text: string) => text.replaceAll('\r', '');
const loading: Load = { status: 'loading' };
export function landingView(
  programs: Load,
  curricula: Readonly<Record<string, Load>>,
  coop: Load,
) {
  const parsed =
    programs.status === 'ready' ? parseProgramList(programs.data) : null;
  const rows = parsed?.kind === 'ok' ? parsed.data : [];
  const featured = FEATURED_PROGRAM_IDS.filter((id) =>
    rows.some((p) => p.program_id === id),
  );
  const entries = featured.map((id) => ({
    id,
    load: Object.hasOwn(curricula, id) ? curricula[id]! : loading,
  }));
  const pending =
    programs.status === 'loading' ||
    coop.status === 'loading' ||
    entries.some((e) => e.load.status === 'loading');
  const relevant = [programs, coop, ...entries.map((e) => e.load)];
  const transient = relevant.some(
    (l) => l.status === 'failed' && isTransient(l.failure),
  );
  const starters = entries.some((e) => e.load.status === 'loading')
    ? []
    : entries.flatMap(({ id, load }) => {
        const c =
          load.status === 'ready' ? parseCurriculum(load.data, id) : null;
        const pick = c?.kind === 'ok' ? semester1Pick(c.data) : null;
        return pick && c?.kind === 'ok'
          ? [{ programId: id, prefix: c.data.prefix, course: pick }]
          : [];
      });
  const preview = coop.status === 'ready' ? parseCoopPreview(coop.data) : null;
  return {
    programs: rows,
    starters,
    coop: preview?.kind === 'ok' ? preview.data : [],
    pending,
    transient,
  };
}
