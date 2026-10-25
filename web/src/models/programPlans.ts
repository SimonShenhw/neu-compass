import type { ProgramPlanDoc } from '../api/programs';
import type { ProgramNode } from '../api/requisites';
import { object } from './searchGuard';
import { programTree } from './requisites';
import {
  hash,
  nonblank,
  nullable,
  officialUrl,
  oneOf,
  planId,
  realDate,
  scope,
  scopeKey,
} from './programGuard';

const invalid = { kind: 'invalid' } as const;
function unmodeled(node: ProgramNode): boolean {
  return node.kind === 'unmodeled' || node.children.some(unmodeled);
}
export function parsePlan(
  value: unknown,
  programId: string,
):
  | { kind: 'ok'; plan: ProgramPlanDoc }
  | { kind: 'invalid' }
  | { kind: 'other_program' } {
  if (
    !object(value) ||
    !scope(value) ||
    !planId(value.plan_id) ||
    !oneOf(value.coverage, ['partial', 'complete']) ||
    !oneOf(value.review_status, ['draft', 'source_checked']) ||
    !nullable(value.checked_by, (v) => nonblank(v, 100)) ||
    !nullable(value.checked_on, realDate) ||
    !officialUrl(value.source_url, value.catalog_year) ||
    !nonblank(value.source_title, 300) ||
    value.source_catalog_year !== value.catalog_year ||
    !nonblank(value.source_excerpt, 6000) ||
    !nullable(value.source_html_sha256, hash) ||
    !realDate(value.captured_on) ||
    !nonblank(value.notes, 2500) ||
    !programTree(value.requirements)
  )
    return invalid;
  if (
    value.review_status === 'source_checked' &&
    (value.checked_by == null || value.checked_on == null)
  )
    return invalid;
  if (value.checked_on != null && String(value.checked_on) < value.captured_on)
    return invalid;
  if (
    value.coverage === 'complete' &&
    (value.review_status !== 'source_checked' || unmodeled(value.requirements))
  )
    return invalid;
  if (value.program_id !== programId) return { kind: 'other_program' };
  return {
    kind: 'ok',
    plan: {
      ...value,
      concentration: value.concentration ?? null,
      checked_by: value.checked_by ?? null,
      checked_on: value.checked_on ?? null,
      source_html_sha256: value.source_html_sha256 ?? null,
    } as unknown as ProgramPlanDoc,
  };
}
export function availablePlans(values: unknown[], programId: string) {
  const notes: string[] = [];
  const valid: ProgramPlanDoc[] = [];
  for (const value of Array.from(values)) {
    const parsed = parsePlan(value, programId);
    if (parsed.kind === 'ok') valid.push(parsed.plan);
    else
      notes.push(
        parsed.kind === 'invalid'
          ? '一份版本化规则格式/来源校验未通过，未显示。'
          : '一份方案与当前项目身份不符，未显示。',
      );
  }
  const ids = new Map<string, number>();
  const scopes = new Map<string, number>();
  for (const plan of valid) {
    ids.set(plan.plan_id, (ids.get(plan.plan_id) ?? 0) + 1);
    const key = scopeKey(plan);
    scopes.set(key, (scopes.get(key) ?? 0) + 1);
  }
  const plans = valid.filter(
    (p) => ids.get(p.plan_id) === 1 && scopes.get(scopeKey(p)) === 1,
  );
  if (plans.length !== valid.length)
    notes.push('重复的方案身份／范围存在歧义，相关版本未显示。');
  return { plans, notes };
}
