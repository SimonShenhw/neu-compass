import {
  boundedText,
  fullMatch,
  integer,
  list,
  object,
  string,
  year,
} from './searchGuard';
import { utcMinute } from './courseDetailFormat';

const relations = [
  'required',
  'any_of_option',
  'select_candidate',
  'optional_branch',
  'excluded',
  'open_pool',
] as const;
export type Relation = (typeof relations)[number];
export interface Placement {
  path: string[];
  relation: Relation;
  under_any_of: boolean;
  activate_when: string[];
  min_courses: number | null;
  min_credits: number | null;
  min_areas: number | null;
  areas: string[];
}
export interface PlanContext {
  program_id: string;
  plan_id: string;
  campus: string;
  catalog_year: string;
  pathway: 'standard' | 'align' | 'bridge';
  concentration: string | null;
  plan_content_sha256: string;
  coverage: 'partial' | 'complete';
  review_status: 'source_checked';
  checked_on: string;
  captured_on: string;
  source_catalog_year: string;
  source_url: string;
  placements: Record<string, Placement[]>;
  placements_omitted: Record<string, number>;
}
function date(v: unknown): v is string {
  if (!string(v) || !fullMatch(/\d{4}-\d{2}-\d{2}/, v)) return false;
  try {
    utcMinute(v + 'T00:00:00');
    return true;
  } catch {
    return false;
  }
}
const texts = (v: unknown, min: number, max: number) =>
  list(v, (x): x is string => boundedText(x, min, max));
function placement(v: unknown): Placement | null {
  if (
    !object(v) ||
    typeof v.relation !== 'string' ||
    !relations.includes(v.relation as Relation)
  )
    return null;
  const path = texts(v.path, 1, 300),
    areas = texts(v.areas === undefined ? [] : v.areas, 1, 300);
  const conditions = list(
    v.activate_when === undefined ? [] : v.activate_when,
    (x): x is string => boundedText(x, 1, 500) && x.trim() !== '',
  );
  const under = v.under_any_of === undefined ? false : v.under_any_of;
  const courses = v.min_courses ?? null,
    credits = v.min_credits ?? null,
    minAreas = v.min_areas ?? null;
  if (
    !path ||
    path.length < 1 ||
    path.length > 8 ||
    !areas ||
    areas.length > 40 ||
    !conditions ||
    conditions.length > 8 ||
    typeof under !== 'boolean' ||
    (courses !== null && !integer(courses, 1, 100)) ||
    (credits !== null && !integer(credits, 1, 200)) ||
    (minAreas !== null && !integer(minAreas, 1, 40))
  )
    return null;
  return {
    path,
    relation: v.relation as Relation,
    under_any_of: under,
    activate_when: conditions,
    areas,
    min_courses: courses,
    min_credits: credits,
    min_areas: minAreas,
  };
}
export function parsePlanContext(
  v: unknown,
  courseIds: readonly string[],
): PlanContext | null {
  if (
    !object(v) ||
    !string(v.program_id) ||
    !fullMatch(/[a-z0-9][a-z0-9-]{0,63}/, v.program_id) ||
    !string(v.plan_id) ||
    !fullMatch(/[a-z0-9][a-z0-9-]{0,99}/, v.plan_id) ||
    !string(v.campus) ||
    !fullMatch(/[a-z][a-z0-9-]{0,39}/, v.campus) ||
    !year(v.catalog_year) ||
    (v.pathway !== 'standard' &&
      v.pathway !== 'align' &&
      v.pathway !== 'bridge') ||
    (v.concentration !== null &&
      !(
        boundedText(v.concentration, 1, 100) && v.concentration.trim() !== ''
      )) ||
    !string(v.plan_content_sha256) ||
    !fullMatch(/[a-f0-9]{64}/, v.plan_content_sha256) ||
    (v.coverage !== 'partial' && v.coverage !== 'complete') ||
    v.review_status !== 'source_checked' ||
    !date(v.checked_on) ||
    !date(v.captured_on) ||
    v.checked_on < v.captured_on ||
    v.source_catalog_year !== v.catalog_year ||
    !string(v.source_url) ||
    !fullMatch(
      /https:\/\/catalog\.northeastern\.edu\/(archive\/\d{4}-\d{4}\/)?graduate\/[a-z0-9/-]+\//,
      v.source_url,
    ) ||
    !object(v.placements) ||
    !object(v.placements_omitted)
  )
    return null;
  const archive = /\/archive\/(\d{4}-\d{4})\//.exec(v.source_url)?.[1];
  if (archive && archive !== v.catalog_year) return null;
  const keys = Object.keys(v.placements),
    omitted = v.placements_omitted;
  if (
    keys.length > 20 ||
    keys.length !== Object.keys(omitted).length ||
    keys.some(
      (k) =>
        !boundedText(k, 1, 100) ||
        !Object.hasOwn(omitted, k) ||
        !integer(omitted[k]),
    ) ||
    new Set(courseIds).size !== keys.length ||
    keys.some((k) => !courseIds.includes(k))
  )
    return null;
  const entries: [string, Placement[]][] = [];
  for (const key of keys) {
    const raw = v.placements[key];
    if (!Array.isArray(raw) || raw.length > 4) return null;
    const values = Array.from(raw).map(placement);
    if (values.some((p) => p === null)) return null;
    entries.push([key, values as Placement[]]);
  }
  return {
    program_id: v.program_id,
    plan_id: v.plan_id,
    campus: v.campus,
    catalog_year: v.catalog_year,
    pathway: v.pathway,
    concentration: v.concentration,
    plan_content_sha256: v.plan_content_sha256,
    coverage: v.coverage,
    review_status: v.review_status,
    checked_on: v.checked_on,
    captured_on: v.captured_on,
    source_catalog_year: v.source_catalog_year,
    source_url: v.source_url,
    placements: Object.fromEntries(entries),
    placements_omitted: Object.fromEntries(
      keys.map((k) => [k, omitted[k] as number]),
    ),
  };
}
const labels: Record<Relation, string> = {
  required: '方案列明的必修课程',
  any_of_option: 'OR 分支中的一个选项',
  select_candidate: '组选候选，并非全部必修',
  optional_branch: '仅适用于可选分支',
  excluded: '本组选明确排除',
  open_pool: '开放前缀／范围，不是匹配证明，仍需向项目核实',
};
export function placementText(p: Placement): string {
  const pieces = [labels[p.relation], p.path.join(' > ')];
  if (p.under_any_of) pieces.push('上层有 OR 分支，不是所有分支共同必修');
  pieces.push(...p.activate_when.map((x) => `条件：${x}`));
  if (p.min_courses !== null) pieces.push(`该组至少 ${p.min_courses} 门`);
  if (p.min_credits !== null) pieces.push(`该组至少 ${p.min_credits} 学分`);
  if (p.min_areas !== null) pieces.push(`该组至少 ${p.min_areas} 领域`);
  if (p.areas.length) pieces.push(`所属领域：${p.areas.join('、')}`);
  return pieces.join('；');
}
