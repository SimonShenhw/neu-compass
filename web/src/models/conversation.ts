import type { Turn } from './chatTurn';
import { isRunning } from './chatTurn';

export function recentHistory(turns: readonly Turn[]) {
  return turns
    .filter((t) => !isRunning(t))
    .flatMap((t) => {
      const content =
        t.status === 'failed'
          ? ''
          : t.text +
            (t.error ? `${t.text ? '\n\n' : ''}⚠️ ${t.error.message}` : '');
      return [
        { role: 'user' as const, content: t.question },
        { role: 'assistant' as const, content },
      ];
    })
    .slice(-6)
    .filter((m) => m.content !== '')
    .map((m) => ({
      ...m,
      content: Array.from(m.content).slice(0, 4000).join(''),
    }));
}
export function contextCourseIds(turns: readonly Turn[]): string[] {
  for (let i = turns.length - 1; i >= 0; i--) {
    const t = turns[i]!;
    if (!isRunning(t) && t.meta?.kind === 'ok' && t.meta.results.length)
      return t.meta.results.slice(0, 10).map((r) => r.course_id);
  }
  return [];
}
