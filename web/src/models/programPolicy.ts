import type {
  PolicyEvidence,
  PolicyFragment,
  ProgramPolicyView,
} from '../api/programs';
import { integer, list, object, string } from './searchGuard';
import {
  hash,
  match,
  nonblank,
  nullable,
  officialUrl,
  oneOf,
  planId,
  realDate,
  scope,
  scopeKey,
} from './programGuard';

const paths = {
  university: 'academic-policies-procedures/',
  khoury: 'computer-information-science/academic-policies-procedures/',
  camd: 'arts-media-design/academic-policies-procedures/',
  engineering: 'engineering/academic-policies-procedures/',
};
function fragment(v: unknown): PolicyFragment | null {
  if (
    !object(v) ||
    !string(v.fragment_id) ||
    !(
      v.source_kind === undefined ||
      v.source_kind === 'paragraph' ||
      v.source_kind === 'list'
    ) ||
    !integer(v.paragraph_index, 0, 299) ||
    !nullable(v.heading, string) ||
    !hash(v.paragraph_sha256) ||
    !nonblank(v.summary, 1500) ||
    !nonblank(v.limitation, 1500) ||
    !string(v.source_paragraph) ||
    v.source_paragraph === ''
  )
    return null;
  return {
    ...v,
    source_kind: v.source_kind ?? 'paragraph',
    heading: v.heading ?? null,
  } as unknown as PolicyFragment;
}
function evidence(
  v: unknown,
  college: string,
  year: string,
  checked: string,
): PolicyEvidence | null {
  if (
    !object(v) ||
    !match(/[a-z0-9][a-z0-9-]{0,79}/, v.policy_id) ||
    !(v.authority === 'university' || v.authority === college) ||
    !object(v.source)
  )
    return null;
  const s = v.source;
  const path = officialUrl(s.url, year);
  const prefix = paths[v.authority as keyof typeof paths];
  if (
    !path ||
    !prefix ||
    !path.startsWith(prefix) ||
    path === prefix ||
    s.catalog_year !== year ||
    !match(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z/, s.captured_at) ||
    !nonblank(s.page_title, 300) ||
    !hash(s.sha256) ||
    checked < s.captured_at.slice(0, 10) ||
    !Array.isArray(v.fragments) ||
    v.fragments.length < 1 ||
    v.fragments.length > 30
  )
    return null;
  const fragments = Array.from(v.fragments).map(fragment);
  if (fragments.some((f) => !f)) return null;
  const normalized = fragments as PolicyFragment[];
  if (
    new Set(normalized.map((f) => f.fragment_id)).size !== normalized.length ||
    new Set(
      normalized.map((f) => JSON.stringify([f.source_kind, f.paragraph_index])),
    ).size !== normalized.length
  )
    return null;
  return { ...v, fragments: normalized } as unknown as PolicyEvidence;
}
export function parsePolicyView(
  value: unknown,
): { kind: 'ok'; view: ProgramPolicyView } | { kind: 'invalid' } {
  const invalid = { kind: 'invalid' } as const;
  if (
    !object(value) ||
    !planId(value.plan_id) ||
    !scope(value.scope) ||
    !hash(value.plan_content_sha256) ||
    !oneOf(value.status, [
      'ready',
      'not_linked',
      'draft',
      'stale',
      'unavailable',
      'unusable',
    ]) ||
    !(value.link == null || object(value.link)) ||
    !nullable(value.checked_by, string) ||
    !nullable(value.checked_on, realDate) ||
    !Array.isArray(value.policies)
  )
    return invalid;
  const normalizedScope = {
    ...value.scope,
    concentration: value.scope.concentration ?? null,
  };
  if (value.status !== 'ready') {
    if (
      value.policies.length ||
      value.link != null ||
      value.checked_by != null ||
      value.checked_on != null
    )
      return invalid;
    return {
      kind: 'ok',
      view: {
        ...value,
        scope: normalizedScope,
        link: null,
        checked_by: null,
        checked_on: null,
      } as unknown as ProgramPolicyView,
    };
  }
  const link = value.link;
  if (
    !object(link) ||
    !nonblank(value.checked_by, 100) ||
    !realDate(value.checked_on) ||
    !value.policies.length ||
    !scope(link) ||
    link.plan_id !== value.plan_id ||
    scopeKey(link) !== scopeKey(value.scope) ||
    link.plan_content_sha256 !== value.plan_content_sha256 ||
    !oneOf(link.home_college, ['khoury', 'camd', 'engineering'])
  )
    return invalid;
  const ids = list(link.policy_ids, (v): v is string => string(v) && v !== '');
  if (!ids?.length || new Set(ids).size !== ids.length) return invalid;
  const catalogYear = value.scope.catalog_year;
  const policies = Array.from(value.policies).map((p) =>
    evidence(
      p,
      String(link.home_college),
      catalogYear,
      value.checked_on as string,
    ),
  );
  if (policies.some((p) => !p)) return invalid;
  const normalized = policies as PolicyEvidence[];
  if (
    JSON.stringify(ids) !==
      JSON.stringify(normalized.map((p) => p.policy_id)) ||
    new Set(normalized.map((p) => p.source.url)).size !== normalized.length
  )
    return invalid;
  return {
    kind: 'ok',
    view: {
      ...value,
      scope: normalizedScope,
      link: { ...link, concentration: link.concentration ?? null },
      policies: normalized,
    } as unknown as ProgramPolicyView,
  };
}
