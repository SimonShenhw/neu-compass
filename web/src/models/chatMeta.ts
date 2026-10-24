import type { ChatResult } from '../api/chat';
import { evidence } from './courseDetail';
import type { ParsedAnswerEvidence } from './courseDetail';
import { integer, list, object, string, year, fullMatch } from './searchGuard';
import { utcMinute } from './courseDetailFormat';
import { scaledEven, roundEven } from './compare';

export type ParsedResult = ChatResult & {
  evidence: ParsedAnswerEvidence | null;
  requisites: unknown;
};
export type ParsedMeta =
  | { kind: 'invalid' }
  | {
      kind: 'ok';
      matched_via: string;
      results: ParsedResult[];
      notices: unknown;
      plan_context: unknown;
    };
export const BAD_RESULTS = '相关课程的格式不对，没有显示。';
function result(v: unknown): v is ChatResult {
  return (
    object(v) &&
    string(v.course_id) &&
    v.course_id.length > 0 &&
    string(v.primary_code) &&
    v.primary_code.length > 0 &&
    string(v.primary_name) &&
    v.primary_name.length > 0 &&
    typeof v.score === 'number' &&
    Number.isFinite(v.score)
  );
}
export function parseChatMeta(v: unknown): ParsedMeta {
  if (!object(v) || !string(v.matched_via)) return { kind: 'invalid' };
  const results = list(v.results, result);
  if (!results) return { kind: 'invalid' };
  return {
    kind: 'ok',
    matched_via: v.matched_via,
    notices: v.notices,
    plan_context: v.plan_context,
    results: results.map((r) => ({
      ...r,
      evidence: evidence(r.answer_evidence),
      requisites: object(r.answer_evidence)
        ? r.answer_evidence.requisites
        : undefined,
    })),
  };
}
export function scoreText(score: number) {
  const sign = score < 0 || Object.is(score, -0) ? '-' : '';
  const digits = scaledEven(Math.abs(score), 3).toString().padStart(4, '0');
  return `${sign}${digits.slice(0, -3)}.${digits.slice(-3)}`;
}
export function scorePercent(score: number, top: number) {
  return Math.min(
    100,
    Math.max(0, Math.max(top > 0 ? roundEven((100 * score) / top) : 50, 8)),
  );
}
export const COMPACT_WARNINGS = [
  'catalog_metadata_conflict',
  'field_evidence_value_conflict',
  'program_seed_unverified',
  'synthetic_record_not_real_course',
  'prerequisite_logic_unavailable',
  'extracted_evidence_not_official_facts',
  'requisites_differ_by_catalog_year',
  'requisite_clause_unparsed',
  'structured_requisites_unusable',
  'requisite_year_not_recorded',
] as const;
const department = (v: unknown): v is string =>
  string(v) &&
  fullMatch(
    /https:\/\/catalog\.northeastern\.edu\/course-descriptions\/[a-z]{2,8}\//,
    v,
  );
function edition(v: unknown): v is { catalog_year: string } {
  if (
    !object(v) ||
    !year(v.catalog_year, false) ||
    !department(v.catalog_url) ||
    !string(v.captured_at)
  )
    return false;
  try {
    utcMinute(v.captured_at);
  } catch {
    return false;
  }
  return [v.prerequisite, v.corequisite].every(
    (x) =>
      object(x) &&
      string(x.status) &&
      ['not_listed', 'parsed', 'unparsed'].includes(x.status),
  );
}
export function requisiteYearsLine(v: unknown): string | null {
  if (
    !object(v) ||
    !string(v.storage) ||
    !['available', 'schema_missing', 'schema_unusable'].includes(v.storage)
  )
    return null;
  const editions = list(v.editions === undefined ? [] : v.editions, edition);
  const omitted = v.editions_omitted === undefined ? 0 : v.editions_omitted;
  const unusable = v.unusable_records === undefined ? 0 : v.unusable_records;
  const others =
    v.other_years_recorded === undefined ? 0 : v.other_years_recorded;
  const selected = v.selected_year ?? null;
  if (
    !editions ||
    editions.length > 3 ||
    !integer(omitted) ||
    !integer(unusable) ||
    !integer(others) ||
    (selected !== null && !year(selected))
  )
    return null;
  const years = editions.map((e) => e.catalog_year);
  if (
    years.some((y, i) => i > 0 && y >= years[i - 1]!) ||
    (v.storage !== 'available' &&
      (editions.length !== 0 || omitted !== 0 || unusable !== 0)) ||
    (selected !== null &&
      years.includes(selected) &&
      (editions.length !== 1 || omitted !== 0)) ||
    (selected === null && others !== 0) ||
    (selected !== null &&
      !years.includes(selected) &&
      others !== editions.length + omitted) ||
    (omitted > 0 && editions.length !== 3)
  )
    return null;
  if (selected !== null) {
    if (v.storage !== 'available') return null;
    if (!years.includes(selected))
      return `所选方案 Catalog ${selected} 没有可用的课程块规则${editions.length ? '；展示的其他年份不能替代' : ''}。`;
    return `先修/共修规则：所选方案 Catalog ${selected} 的课程块原文${others > 0 ? `；另有 ${others} 个其他年份未用于本次解释` : ''}（不判断注册适用年度）`;
  }
  return years.length
    ? `先修/共修规则：已存 ${years.map((y) => `Catalog ${y}`).join('、')} 的课程块原文${omitted > 0 ? `，另有 ${omitted} 个更早年份没有列出` : ''}（非实时核验，不判断能否注册）`
    : null;
}
