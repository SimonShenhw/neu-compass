import type { ApiFailure } from '../api/load';
import type { PolicyScope } from '../api/programs';
import { ApiError, apiErrorMessage as errorMessage } from '../api/client';

export const PLAN_PLACEHOLDER = '请明确选择；不默认最新版本';
export const PLAN_LABEL = '选择目录版本与路径（不自动判定你的适用年度）';
export const PROGRAM_INTRO =
  '版本化规则与旧课程表分开浏览；规则展示不是个人选课资格审核';
export const collapseSpace = (text: string) =>
  text
    // Python split includes these control separators; JS \s has a different set.
    .split(
      // eslint-disable-next-line no-control-regex
      /[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+/,
    )
    .filter(Boolean)
    .join(' ');
export function scopeLabel(plan: PolicyScope) {
  const path = { standard: '普通 MS', align: 'Align', bridge: 'Bridge' }[
    plan.pathway as 'standard' | 'align' | 'bridge'
  ];
  return `${plan.campus} · Catalog ${plan.catalog_year} · ${path} · ${plan.concentration ?? '共同部分／未限定 concentration'}`;
}
export function requirementLabel(type: string) {
  const labels = new Map([
    ['core', '核心 · core'],
    ['foundation', '基础 · foundation'],
    ['elective_pool', '选修池 · elective'],
    ['capstone', '毕业项目 · capstone'],
  ]);
  return labels.get(type) ?? '基础 · foundation';
}
export const semesterHeading = (n: number | null) =>
  n === null
    ? '未提供推荐学期（不等于任意学期都可修）'
    : `旧课程表：第 ${n} 学期建议（未核验）`;
export const capturedText = (text: string) => text.replace(/Z$/, '+00:00');
export const apiErrorMessage = (failure: ApiFailure) =>
  errorMessage(new ApiError(failure.status, failure));
export interface SharePlan extends PolicyScope {
  plan_id: string;
  plan_content_sha256: string;
}
function quote(text: string) {
  return encodeURIComponent(text)
    .replace(
      /[!'()*]/g,
      (c) => `%${c.charCodeAt(0).toString(16).toUpperCase()}`,
    )
    .replaceAll('%20', '+');
}
export function shareUrl(
  base: string,
  programId: string,
  link: SharePlan | null,
) {
  const pairs = link
    ? [
        ['plan_v', '1'],
        ['program', programId],
        ['plan', link.plan_id],
        ['campus', link.campus],
        ['catalog_year', link.catalog_year],
        ['pathway', link.pathway],
        ['concentration', JSON.stringify(link.concentration)],
        ['plan_revision', link.plan_content_sha256],
      ]
    : [['program', programId]];
  return `${base.replace(/\/+$/, '')}/?${pairs.map(([k, v]) => `${quote(k!)}=${quote(v!)}`).join('&')}`;
}
