import {
  generalNumber,
  noticeLine as compareNoticeLine,
  roundEven,
  scaledEven,
  when,
} from './compare';

export const pyG = generalNumber;
export const utcMinute = when;
export const percentEven = (weight: number) =>
  Object.is(weight, -0) ? '-0' : String(roundEven(weight * 100));
export function confidenceEven(value: number) {
  const sign = Object.is(value, -0) ? '-' : '';
  const digits = scaledEven(value, 2).toString().padStart(3, '0');
  return `${sign}${digits.slice(0, -2)}.${digits.slice(-2)}`;
}
export function oneLine(value: string) {
  // Normalize Python's rare record separators to LINE SEPARATOR, not LF:
  // replacing them with LF would incorrectly merge a preceding CR into CRLF.
  const separated = value
    .replaceAll('\x1c', '\u2028')
    .replaceAll('\x1d', '\u2028')
    .replaceAll('\x1e', '\u2028');
  const lines = separated.split(/\r\n|[\n\r\v\f\x85\u2028\u2029]/);
  if (lines.at(-1) === '') lines.pop();
  return lines.join(' ');
}
export function noticeLine(
  warnings: readonly string[],
  exclude: readonly string[] = [],
) {
  return compareNoticeLine(warnings.filter((code) => !exclude.includes(code)));
}
export const OVERVIEW_EXCLUDED = [
  'catalog_source_unavailable',
  'requisites_differ_by_catalog_year',
  'requisite_clause_unparsed',
  'structured_requisites_unusable',
] as const;
export const FIELD_LABELS: Readonly<Record<string, string>> = {
  catalog_description: '官方描述',
  credits: '学分',
  term: '开课学期',
  delivery_mode: '授课方式',
  professor: '教师',
  prereqs: '结构化先修信息',
  topics_covered: '结构化主题',
  skill_tags: '技能标签',
  workload_hours_per_week: '每周工作量',
  difficulty_score: '难度',
  grading_components: '考核构成',
  career_relevance: '职业方向',
};
export const WARNING_LABELS: Readonly<Record<string, string>> = {
  catalog_source_unavailable:
    '未附可追溯的目录快照，不能将检索文本当作官方描述。',
  catalog_retrieval_date_unknown:
    '目录抓取日期未记录；导入时间不是抓取时间，也不证明当前开课。',
  extracted_evidence_not_official_facts:
    '软字段是来源支持的抽取/评价，不是官方事实；抽取置信度不等于事实概率。',
  topics_source_unavailable: '结构化主题未附来源，需核实。',
  prerequisite_logic_unavailable:
    '先修代码未保留 AND/OR 语义，不能据此判断所有/任一必需。',
  requisites_differ_by_catalog_year:
    '不同 Catalog 年份记录的先修/共修规则不一样，要看你适用哪一年。',
  requisite_clause_unparsed:
    '有一段先修/共修原文没能解析成规则，只能照原文核对。',
  structured_requisites_unusable:
    '有已存的年度先修/共修规则读不出来或校验没通过；不能当作那一年没有要求。',
  requisite_year_not_recorded:
    '所选方案的 Catalog 年度没有可用课程块规则，其他年份不能代替所选年度。',
  program_seed_unverified:
    '培养方案关系来自未核验 seed，不是正式 Plan of Study 或选课资格保证。',
  catalog_metadata_conflict:
    '目录快照与课程记录的学分不一致，需向官方核实，不能静默合并。',
  field_evidence_value_conflict:
    '数值估计与证据支持值不一致，需核验，不能当作已确定事实。',
  synthetic_record_not_real_course: '此记录为合成测试数据，不是实际课程推荐。',
};
export const labelFor = (
  labels: Readonly<Record<string, string>>,
  code: string,
) => (Object.hasOwn(labels, code) ? labels[code]! : code);
const SOURCE_KINDS = [
  ['rmp_review_', 'RateMyProfessors 教师评价'],
  ['reddit_', 'Reddit 讨论'],
  ['syllabus_', '课程大纲'],
  ['synthetic_seed_', '合成测试数据'],
  ['catalog_', '抽取时用的课程文本'],
] as const;
export function sourceKind(id: string) {
  return (
    SOURCE_KINDS.find(([prefix]) => id.startsWith(prefix))?.[1] ?? '其他来源'
  );
}
export function sourceSummary(ids: readonly string[]) {
  const counts = new Map<string, number>();
  for (const id of new Set(ids)) {
    const kind = sourceKind(id);
    counts.set(kind, (counts.get(kind) ?? 0) + 1);
  }
  // Stable sort preserves first-seen source-kind order for ties, like Counter.most_common.
  return [...counts]
    .sort((a, b) => b[1] - a[1])
    .map(([kind, count]) => `${kind} ${count} 条`)
    .join('、');
}
export function snapshotDigest(id: string) {
  return /^catalog:[a-f0-9]{64}$/.test(id) ? id.slice(8) : null;
}
export function evidenceValue(value: unknown): string {
  if (typeof value === 'string' || typeof value === 'number')
    return String(value);
  if (
    Array.isArray(value) &&
    Array.from(value).every((item) => typeof item === 'string')
  )
    return value.join('、');
  try {
    return JSON.stringify(value) ?? String(value);
  } catch {
    return String(value);
  }
}
