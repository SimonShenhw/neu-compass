import type { CoopRecord } from '../api/coop';
import { integer, object, string } from './searchGuard';

export type CoopPreview = Pick<
  CoopRecord,
  | 'company'
  | 'role'
  | 'visibility_level'
  | 'interview_summary'
  | 'technical_questions'
  | 'salary_range_usd'
>;
export function parseCoopPreview(
  value: unknown,
): { kind: 'ok'; data: CoopPreview[] } | { kind: 'invalid' } {
  if (!Array.isArray(value)) return { kind: 'invalid' };
  const rows: CoopPreview[] = [];
  for (const v of Array.from(value.slice(0, 2))) {
    if (
      !object(v) ||
      !string(v.company) ||
      !string(v.role) ||
      !integer(v.visibility_level, 0, 2) ||
      ![v.interview_summary, v.technical_questions, v.salary_range_usd].every(
        (x) => x == null || string(x),
      )
    )
      return { kind: 'invalid' };
    rows.push({
      company: v.company,
      role: v.role,
      visibility_level: v.visibility_level as 0 | 1 | 2,
      interview_summary:
        (v.interview_summary as string | null | undefined) ?? null,
      technical_questions:
        (v.technical_questions as string | null | undefined) ?? null,
      salary_range_usd:
        (v.salary_range_usd as string | null | undefined) ?? null,
    });
  }
  return { kind: 'ok', data: rows };
}
