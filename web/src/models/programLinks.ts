// Old links to the program pages (R4c; R0 11 and 16.3), read as Streamlit reads them (app/deep_links.py,
// app/program_plan_links.py): /?program=<ref> names a program, and the eight keys of /?plan_v=1&program=… name one
// exact plan at one content version. A link only says where to go: what it opens is checked against the API's answer,
// and no plan other than exactly the one shared is ever chosen in its place.
import type { ProgramPlanDoc, ProgramSummary } from '../api/programs';
import { planRevisions } from './chatPlans';
import { refLabel } from './coursePath';
import { hash, match, nonblank, oneOf, scopeKey } from './programGuard';
import { parsePlan } from './programPlans';
import { object, year } from './searchGuard';

// Streamlit's QUERY_FIELDS, in its order.
const FIELDS = [
  'plan_v',
  'program',
  'plan',
  'campus',
  'catalog_year',
  'pathway',
  'concentration',
  'plan_revision',
] as const;
// Streamlit's size budget for the eight values together, in characters.
const MAX_LINK_CHARS = 2048;
const PATHWAYS = ['standard', 'align', 'bridge'] as const;

// The exact plan a link names (schemas/plan_selection.py PlanSelection).
export interface PlanLink {
  program_id: string;
  plan_id: string;
  campus: string;
  catalog_year: string;
  pathway: (typeof PATHWAYS)[number];
  concentration: string | null;
  plan_content_sha256: string;
}
export type PlanLinkStatus =
  'ready' | 'missing' | 'stale' | 'draft' | 'unusable' | 'unavailable';

// Any plan key but `program` makes the address a plan link, and a broken one stays one (has_plan_link): it is never
// read as a /?program= link instead.
export function hasPlanLink(params: URLSearchParams): boolean {
  return FIELDS.some((key) => key !== 'program' && params.has(key));
}

// read_plan_link: each key exactly once, the values within the budget, `concentration` as JSON null or a JSON string,
// then each field as PlanSelection takes it. A link that also carries `course` is broken: a plan and a course are
// different destinations. Null when anything is off.
export function readPlanLink(params: URLSearchParams): PlanLink | null {
  if (params.has('course')) return null;
  const values: string[] = [];
  let size = 0;
  for (const key of FIELDS) {
    const all = params.getAll(key);
    if (all.length !== 1) return null;
    size += Array.from(all[0]!).length;
    if (size > MAX_LINK_CHARS) return null;
    values.push(all[0]!);
  }
  const [version, programId, planId, campus, catalogYear, pathway, scoped] =
    values as [string, string, string, string, string, string, string];
  const revision = values[7]!;
  let concentration: string | null;
  if (scoped === 'null') concentration = null;
  else if (scoped.startsWith('"') && scoped.endsWith('"')) {
    let parsed: unknown;
    try {
      parsed = JSON.parse(scoped);
    } catch {
      return null;
    }
    if (typeof parsed !== 'string') return null;
    concentration = parsed;
  } else return null;
  if (
    version !== '1' ||
    !match(/[a-z0-9][a-z0-9-]{0,63}/, programId) ||
    !match(/[a-z0-9][a-z0-9-]{0,99}/, planId) ||
    !match(/[a-z][a-z0-9-]{0,39}/, campus) ||
    !year(catalogYear) ||
    !oneOf(pathway, PATHWAYS) ||
    (concentration !== null && !nonblank(concentration, 100)) ||
    !hash(revision)
  )
    return null;
  return {
    program_id: programId,
    plan_id: planId,
    campus,
    catalog_year: catalogYear,
    pathway: pathway as PlanLink['pathway'],
    concentration,
    plan_content_sha256: revision,
  };
}

// resolve_plan_link, on the program's answer read fresh: every document must be a plan of this program and each ID and
// scope must appear once, or nothing in the list can be trusted to be the plan shared; that plan must then have the
// same scope at the same content version (plan_revisions, the API's content_hash) and be checked against its sources.
// A version the answer does not give cannot be confirmed either way.
export function checkPlanLink(body: unknown, link: PlanLink): PlanLinkStatus {
  if (!object(body) || body.program_id !== link.program_id) return 'unusable';
  if (body.plan_schema_available !== true) return 'unavailable';
  const documents = body.plans;
  if (!Array.isArray(documents) || documents.length > 100) return 'unusable';
  const plans: ProgramPlanDoc[] = [];
  for (const value of documents) {
    const read = parsePlan(value, link.program_id);
    if (read.kind !== 'ok') return 'unusable';
    plans.push(read.plan);
  }
  if (
    new Set(plans.map((p) => p.plan_id)).size !== plans.length ||
    new Set(plans.map((p) => scopeKey(p))).size !== plans.length
  )
    return 'unusable';
  const plan = plans.find((p) => p.plan_id === link.plan_id);
  if (plan === undefined) return 'missing';
  const revisions = planRevisions(body);
  if (!Object.hasOwn(revisions, plan.plan_id)) return 'unusable';
  if (
    scopeKey(plan) !== scopeKey(link) ||
    revisions[plan.plan_id] !== link.plan_content_sha256
  )
    return 'stale';
  if (plan.review_status !== 'source_checked') return 'draft';
  return 'ready';
}

// match_program_ref: a /?program= link names a program by its ID or by its prefix, either in any case; a prefix two
// programs share names neither.
export function matchProgramRef(
  ref: string,
  rows: readonly ProgramSummary[],
): string | null {
  const needle = ref.trim().toLowerCase();
  if (needle === '') return null;
  const byId = rows.find((row) => row.program_id.toLowerCase() === needle);
  if (byId) return byId.program_id;
  const byPrefix = rows.filter((row) => row.prefix.toLowerCase() === needle);
  return byPrefix.length === 1 ? byPrefix[0]!.program_id : null;
}

// What the program pages say about the link they were opened from: Streamlit's MESSAGES, without the emoji or inside
// words such as 「旧 seed」. A broken link opens the list; every other outcome opens the program, with no plan chosen
// unless it is exactly the one shared (the user's choice, 10-27).
export const PLAN_LINK_NOTICES = {
  invalid:
    '这个方案分享链接的参数缺失、重复或互相冲突，没有选择方案；请在下面打开项目，再自己选择。',
  missing:
    '分享的这份方案已经不在了；没有改选同一范围或同一系列的其他版本，请自己选择。',
  stale: '分享的方案的范围或内容版本已经变了；没有自动换成新版本，请重新选择。',
  unusable:
    '这个项目的方案身份、范围或格式校验没有通过，无法确认分享的方案；没有选择方案。',
  unavailable: '现在取不到这个项目的版本化方案；没有用其他年度或旧课程表代替。',
  draft: '分享的方案还没有完成来源对照；没有按链接选上。',
  ready:
    '已经按分享链接选上这份方案和它的内容版本；这不是你的适用年度或个人资格的确认。',
  retry: '暂时没能核对分享链接里的方案；可以点「刷新方案及政策证据」再试一次。',
} as const;

export const programNotFound = (ref: string) =>
  `没有找到链接里的培养方案「${refLabel(ref)}」；下面是全部培养方案。`;
