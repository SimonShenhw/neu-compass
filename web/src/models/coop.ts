import type { CoopRecord, CoopUploadRequest } from '../api/coop';
export type { CoopRecord } from '../api/coop';

export const industryLabels: Readonly<Record<string, string>> = {
  quant_fintech: '量化 / 金融科技',
  big_tech: '大型科技公司',
  biotech_health: '生物科技 / 医疗',
  startup: '创业公司',
  consulting: '咨询',
  other: '其他',
};
export const industryOptions = [
  { value: 'all', label: '全部行业' },
  ...Object.entries(industryLabels).map(([value, label]) => ({ value, label })),
  { value: 'missing', label: '未提供行业' },
];
export function filterCoops(
  records: readonly CoopRecord[],
  query: string,
  industry: string,
) {
  const needle = query.trim().toLowerCase();
  return records.filter((record) => {
    const matchesIndustry =
      industry === 'all' ||
      (industry === 'missing'
        ? record.industry === null
        : record.industry === industry);
    const matchesQuery = `${record.company} ${record.role}`
      .toLowerCase()
      .includes(needle);
    return matchesIndustry && matchesQuery;
  });
}
export function industryName(value: string) {
  return Object.hasOwn(industryLabels, value) ? industryLabels[value] : value;
}

export const fieldLabels = {
  company: '公司 *',
  role: '职位 *',
  coop_term: 'Co-op 学期（例如 Summer 2025）',
  industry: '行业',
  duration_months: '时长（月）',
  related_courses: '相关课程（用逗号分隔课程代码，例如 CS 6140, DS 5220）',
  interview_summary: '面试经过（请先去掉姓名、联系方式等个人信息）',
  technical_questions: '技术问题（请先去掉个人信息）',
  salary_range_usd: '薪资区间（例如 $30-35/hr，可不填）',
} satisfies Record<keyof CoopUploadRequest, string>;
export type CoopField = keyof typeof fieldLabels;
export type CoopDraft = Record<CoopField, string>;
export type FieldErrors = Partial<Record<CoopField, string>>;
export const emptyDraft: CoopDraft = {
  company: '',
  role: '',
  coop_term: '',
  industry: '',
  duration_months: '',
  related_courses: '',
  interview_summary: '',
  technical_questions: '',
  salary_range_usd: '',
};
export const invalidMessage = '有一项不符合要求，请检查后再提交。';
const longFields = [
  'interview_summary',
  'technical_questions',
  'salary_range_usd',
] as const;
export function prepareSubmission(draft: CoopDraft): {
  errors: FieldErrors;
  request: CoopUploadRequest | null;
} {
  const errors: FieldErrors = {};
  for (const name of ['company', 'role'] as const)
    if (!draft[name].trim()) errors[name] = '公司和职位是必填项。';
  const duration =
    draft.duration_months.trim() === '' ? null : Number(draft.duration_months);
  if (
    duration !== null &&
    (!Number.isInteger(duration) || duration < 1 || duration > 8)
  )
    errors.duration_months = '时长只能是 1–8 的整数，或留空。';
  for (const name of longFields)
    if (Array.from(draft[name].trim()).length > 10000)
      errors[name] = '最多 10,000 字。';
  const industry = draft.industry;
  if (industry !== '' && !Object.hasOwn(industryLabels, industry))
    errors.industry = invalidMessage;
  if (Object.keys(errors).length) return { errors, request: null };
  const nullable = (value: string) => value.trim() || null;
  return {
    errors,
    request: {
      company: draft.company.trim(),
      role: draft.role.trim(),
      coop_term: nullable(draft.coop_term),
      industry:
        industry === '' ? null : (industry as CoopUploadRequest['industry']),
      duration_months: duration,
      related_courses: [
        ...new Set(
          draft.related_courses
            .split(/[,，、]/)
            .map((code) => code.trim())
            .filter(Boolean),
        ),
      ],
      interview_summary: nullable(draft.interview_summary),
      technical_questions: nullable(draft.technical_questions),
      salary_range_usd: nullable(draft.salary_range_usd),
    },
  };
}
export function errorField(detail: string | undefined): CoopField | null {
  const name = detail?.split(':', 1)[0];
  return name && Object.hasOwn(fieldLabels, name) ? (name as CoopField) : null;
}
export const outcomeMessages = {
  pending: '已私有收集，等待人工脱敏审核；尚未公开，也未新增贡献奖励。',
  approved: '已审核，等待至少两个不同贡献者的同组经历齐备后公开。',
  published: '已审核并公开；贡献奖励以服务端计数为准。',
  rejected: '此提交已被审核拒绝；未公开，请联系审核员处理。',
};
export function failureMessage(status: number, hasBody: boolean) {
  if (status === 401) return '登录已经失效，请重新登录后再提交。';
  if (status === 422) return invalidMessage;
  if (status === 503 || !hasBody)
    return '投稿暂时提交不了，请稍后再试。你填的内容还在。';
  return '提交没有成功，请稍后再试。';
}
