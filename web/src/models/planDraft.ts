import type { ApiFailure } from '../api/load';
import type { DraftAnswer, DraftNode, DraftNoticeKind } from '../api/draft';
import { apiErrorMessage } from './programFormat';
import { hash } from './programGuard';
import { boundedText, fullMatch, integer, object, string } from './searchGuard';

// R4b: the draft's answer comes from the API (POST …/draft), which checks the typed codes, re-reads the draft and
// evaluates the plan; the page only checks the answer's shape and shows it. The reference parser is answer_ok in
// draft_fixtures/expected_draft.py (spec section 4), checked against the API's own model on every fixture.
export const MAX_DRAFT_COURSES = 20;
export const DRAFT_INPUT_MAX = 4000;

const invalid = { kind: 'invalid' } as const;
const CODE = /[A-Z]{2,4} [0-9]{4}[A-Z]?/; // ASCII digits only, as the API's code pattern.
const NOTICE_KINDS: readonly DraftNoticeKind[] = [
  'course_gone',
  'duplicate_code',
  'too_many_codes',
  'invalid_format',
  'invalid_format_more',
  'all_present',
  'over_limit',
  'not_found',
  'ambiguous',
  'cross_listed_twin',
  'also_matches',
  'primary_code',
  'invalid_record',
  'nothing_new',
];
const STATUSES: readonly unknown[] = [
  'met',
  'missing',
  'unknown',
  'not_evaluated',
  null,
];
const MAX_DEPTH = 20; // The root is depth 0; plans go 8 deep at most.

const count = (v: unknown) => integer(v, 0);
const stringList = (v: unknown, most = Infinity): v is string[] =>
  Array.isArray(v) && v.length <= most && Array.from(v).every(string);
const listOf = (v: unknown, most: number, item: (v: unknown) => boolean) =>
  Array.isArray(v) && v.length <= most && Array.from(v).every(item);

function course(v: unknown) {
  return (
    object(v) &&
    boundedText(v.course_id, 1, 200) &&
    string(v.code) &&
    fullMatch(CODE, v.code) &&
    boundedText(v.name, 1, 500) &&
    // The key must be there; null is unknown credits, and true is not a number of credits.
    Object.hasOwn(v, 'credits') &&
    (v.credits === null || integer(v.credits, 0, 12))
  );
}
function notice(v: unknown) {
  return (
    object(v) &&
    NOTICE_KINDS.includes(v.kind as DraftNoticeKind) &&
    (v.level === 'warning' || v.level === 'info') &&
    string(v.text) &&
    v.text !== '' &&
    listOf(
      v.candidates,
      10,
      (c) => object(c) && string(c.code) && string(c.name),
    ) &&
    count(v.candidates_omitted)
  );
}
function node(v: unknown, depth: number): boolean {
  return (
    object(v) &&
    depth <= MAX_DEPTH &&
    boundedText(v.kind, 1, 32) &&
    boundedText(v.label, 1, 1000) &&
    Object.hasOwn(v, 'status') &&
    STATUSES.includes(v.status) &&
    stringList(v.reasons, 10) &&
    count(v.reasons_omitted) &&
    stringList(v.counted, 20) &&
    stringList(v.possible, 20) &&
    stringList(v.missing, 10) &&
    count(v.missing_omitted) &&
    object(v.shortfall) &&
    Object.values(v.shortfall).every(count) &&
    listOf(v.children, 40, (child) => node(child, depth + 1))
  );
}

// Extra keys are ignored, so a field the API adds later does not make every answer unreadable.
export function parseDraftAnswer(
  value: unknown,
): { kind: 'ok'; answer: DraftAnswer } | { kind: 'invalid' } {
  if (!object(value) || !hash(value.plan_content_sha256)) return invalid;
  const { courses, added, notices, result } = value;
  if (!listOf(courses, MAX_DRAFT_COURSES, course)) return invalid;
  const codes = (courses as { code: string }[]).map((c) => c.code);
  if (new Set(codes).size !== codes.length) return invalid;
  if (
    !stringList(added) ||
    new Set(added).size !== added.length ||
    !added.every((code) => codes.includes(code))
  )
    return invalid;
  if (!listOf(notices, Infinity, notice)) return invalid;
  if (
    !object(result) ||
    !node(result.root, 0) ||
    !stringList(result.unplaced, MAX_DRAFT_COURSES) ||
    !object(result.summary_counts)
  )
    return invalid;
  const counts = result.summary_counts;
  if (!count(counts.met) || !count(counts.missing) || !count(counts.unknown))
    return invalid;
  return { kind: 'ok', answer: value as unknown as DraftAnswer };
}

export const creditsText = (credits: number | null) =>
  credits === null ? '学分未知' : `${credits} 学分`;

// Streamlit's _tree_lines (app/plan_draft_view.py) without the emoji. Maps, not object literals: a kind such as
// "constructor" must not find a word on Object.prototype.
const STATUS_WORDS = new Map<DraftNode['status'], string>([
  ['met', '按你填的满足'],
  ['missing', '还缺'],
  ['unknown', '不确定'],
  ['not_evaluated', '可选分支，不自动判断'],
  [null, '仅列出，不自动判断'],
]);
const OPERATORS = new Map([
  ['all_of', '全部分支（AND）'],
  ['any_of', '任选其一（OR）'],
  ['select', '组选（非全部必修）'],
]);
function treeLines(node: DraftNode, depth: number, out: string[]) {
  const prefix = '  '.repeat(depth);
  const operator = OPERATORS.get(node.kind);
  const title = operator ? `${operator} ${node.label}` : node.label;
  out.push(`${prefix}${STATUS_WORDS.get(node.status)} — ${title}`);
  const certain = node.counted.filter((code) => !node.possible.includes(code));
  for (const [label, codes] of [
    ['按填写计入', certain],
    ['可能计入／学分未知', node.possible],
    ['缺项候选', node.missing],
  ] as const)
    if (codes.length > 0) out.push(`${prefix}  ${label}：${codes.join('、')}`);
  if (node.missing_omitted > 0)
    out.push(`${prefix}  另有 ${node.missing_omitted} 项候选／子项未展开。`);
  for (const reason of node.reasons) out.push(`${prefix}  原因：${reason}`);
  if (node.reasons_omitted > 0)
    out.push(`${prefix}  另有 ${node.reasons_omitted} 项原因未展开。`);
  for (const child of node.children) treeLines(child, depth + 1, out);
}
export function draftTreeLines(node: DraftNode, depth = 0): string[] {
  const out: string[] = [];
  treeLines(node, depth, out);
  return out;
}

// Spec section 8. The four plan-gone reasons never reach the component on the real page: the wiring clears the plan
// choice and R4a's planRevised notice shows instead; the sentence is a fallback. Never the API's detail.
const PLAN_GONE: readonly (string | null)[] = [
  'stale',
  'missing',
  'draft',
  'unusable',
];
const planGone = (failure: ApiFailure) =>
  failure.status === 409 && PLAN_GONE.includes(failure.reason);
export function draftFailureMessage(failure: ApiFailure) {
  if (planGone(failure))
    return '所选方案已经变化或不能再用，草案没有计算；请重新选择方案。';
  if (failure.status === 409 && failure.reason === 'unavailable')
    return '暂时无法核对所选方案，草案没有计算；请稍后重新核对。';
  if (failure.status === 404) return '找不到这个培养方案或方案，草案没有计算。';
  if (failure.status === 422)
    return '草案的内容超出了限制，没有计算；请清空草案后重新添加。';
  return `无法核对草案。${apiErrorMessage(failure)}`;
}
// Another try cannot help when the plan changed or cannot be used, the program is gone or the body is out of bounds.
export const canRetryDraft = (failure: ApiFailure) =>
  !planGone(failure) && failure.status !== 404 && failure.status !== 422;
