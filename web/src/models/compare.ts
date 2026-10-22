import type { CompareColumn } from '../api/course';

export const BAD_CELL = '这一项的数据格式不对，没有显示。';
export const NO_RULES = '没有可用的年度规则；不表示没有先修或共修要求。';
export const rowLabels = [
  '官方目录描述',
  '学生评价里的估计',
  '先修／共修',
  '主题',
  '考核构成',
  '在培养方案里的位置',
  '缺的数据',
] as const;
export type DetailRow = (typeof rowLabels)[number];
export type JsonObject = Record<string, unknown>;
export type Identity = {
  course_id: string;
  primary_code: string;
  primary_name: string;
};
export type DisplayLine = {
  kind: 'main' | 'note';
  text: string;
  notice?: boolean;
  catalogUrl?: string;
};
export type ProgramPlacement = {
  name: string;
  label: string;
  semester: string | null;
};
export type DetailCell = {
  lines: DisplayLine[];
  topics?: string[];
  programs?: ProgramPlacement[];
};
export type CourseHeaderView = {
  identity: Identity;
  metadata: { label: string; value: string }[];
  notice: string | null;
  creditRange: string | null;
};
export const isObject = (value: unknown): value is JsonObject =>
  typeof value === 'object' && value !== null && !Array.isArray(value);
class BadFormat extends Error {}
function object(value: unknown): JsonObject {
  if (!isObject(value)) throw new BadFormat();
  return value;
}
function string(value: unknown): string {
  if (typeof value !== 'string') throw new BadFormat();
  return value;
}
function strings(value: unknown): string[] {
  if (!Array.isArray(value) || !value.every((item) => typeof item === 'string'))
    throw new BadFormat();
  return value;
}
function array(value: unknown): unknown[] {
  if (value == null) return [];
  if (!Array.isArray(value)) throw new BadFormat();
  return value;
}
function optionalString(value: unknown): string | null {
  return value == null ? null : string(value);
}
function number(
  value: unknown,
  min = -Infinity,
  max = Infinity,
): number | null {
  if (value == null) return null;
  if (
    typeof value !== 'number' ||
    !Number.isFinite(value) ||
    value < min ||
    value > max
  )
    throw new BadFormat();
  return value;
}
function integer(value: unknown, min: number, max = Infinity): number | null {
  const result = number(value, min, max);
  if (result !== null && !Number.isInteger(result)) throw new BadFormat();
  return result;
}
const main = (text: string): DisplayLine => ({ kind: 'main', text });
const note = (text: string): DisplayLine => ({ kind: 'note', text });
function guarded<T>(fn: () => T): T | null {
  try {
    return fn();
  } catch (error) {
    if (error instanceof BadFormat) return null;
    throw error;
  }
}
export function courseIdentity(value: unknown): Identity | null {
  return guarded(() => {
    const b = object(value);
    return {
      course_id: string(b.course_id),
      primary_code: string(b.primary_code),
      primary_name: string(b.primary_name),
    };
  });
}
export const warningLabels: Readonly<Record<string, string>> = {
  catalog_source_unavailable: '没有官方目录的存档',
  catalog_retrieval_date_unknown: '目录的抓取日期没有记录',
  extracted_evidence_not_official_facts:
    '工作量、难度等是根据评价的估计，不是官方信息',
  topics_source_unavailable: '主题列表没有来源',
  prerequisite_logic_unavailable: '先修课之间是「都要」还是「任选」不清楚',
  requisites_differ_by_catalog_year:
    '先修/共修规则各年份不一样，要看你的 Catalog 年份',
  requisite_clause_unparsed: '有一段先修/共修原文没能解析，请照原文核对',
  structured_requisites_unusable: '有年度先修/共修规则读不出来，不是没有要求',
  requisite_year_not_recorded: '所选方案年度没有课程块规则，其他年份不能替代',
  program_seed_unverified: '培养方案关系没有核实，不是正式的 Plan of Study',
  catalog_metadata_conflict: '目录学分和课程记录不一致，请向学校核实',
  field_evidence_value_conflict: '有估计值和评价原文对不上，需要核实',
  synthetic_record_not_real_course: '这是测试数据，不是真实课程',
};
const fieldLabels: Readonly<Record<string, string>> = {
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
const evidence = (body: JsonObject): JsonObject | null =>
  body.answer_evidence == null ? null : object(body.answer_evidence);
function warnings(body: JsonObject): string[] {
  const e = evidence(body);
  return e?.warnings == null ? [] : strings(e.warnings);
}
export function noticeLine(
  codes: readonly string[],
  only?: readonly string[],
): string | null {
  const texts = [...new Set(codes)]
    .filter(
      (code) =>
        Object.hasOwn(warningLabels, code) && (!only || only.includes(code)),
    )
    .map((code) => warningLabels[code]);
  return texts.length ? texts.join('；') + '。' : null;
}
function notice(body: JsonObject, only?: readonly string[]): DisplayLine[] {
  const text = noticeLine(warnings(body), only);
  return text ? [{ ...note(text), notice: true }] : [];
}

// Round the exact IEEE-754 value to six decimal significant digits, like Python :g.
// JS toPrecision alone uses the wrong tie rule for exact halves (123456.5).
function scaledEven(value: number, places: number): bigint {
  const view = new DataView(new ArrayBuffer(8));
  view.setFloat64(0, value);
  const bits = view.getBigUint64(0);
  const exponent = Number((bits >> 52n) & 2047n);
  let numerator = (bits & ((1n << 52n) - 1n)) + (exponent ? 1n << 52n : 0n);
  let denominator = 1n;
  const binaryPower = (exponent ? exponent - 1023 : -1022) - 52;
  if (binaryPower >= 0) numerator <<= BigInt(binaryPower);
  else denominator <<= BigInt(-binaryPower);
  if (places >= 0) numerator *= 10n ** BigInt(places);
  else denominator *= 10n ** BigInt(-places);
  const quotient = numerator / denominator,
    remainder = numerator % denominator;
  return (
    quotient +
    (remainder * 2n > denominator ||
    (remainder * 2n === denominator && quotient % 2n === 1n)
      ? 1n
      : 0n)
  );
}
export function generalNumber(value: number): string {
  if (!Number.isFinite(value)) throw new BadFormat();
  if (value === 0) return Object.is(value, -0) ? '-0' : '0';
  const sign = value < 0 ? '-' : '';
  const abs = Math.abs(value);
  let exponent = Math.floor(Math.log10(abs));
  let digits = scaledEven(abs, 5 - exponent).toString();
  if (digits.length > 6) {
    digits = digits.slice(0, -1);
    exponent++;
  }
  if (exponent < -4 || exponent >= 6) {
    const tail = digits.slice(1).replace(/0+$/, '');
    return `${sign}${digits[0]}${tail ? '.' + tail : ''}e${exponent < 0 ? '-' : '+'}${String(Math.abs(exponent)).padStart(2, '0')}`;
  }
  const point = exponent + 1;
  let text =
    point <= 0
      ? '0.' + '0'.repeat(-point) + digits
      : digits.slice(0, point) +
        (point < digits.length ? '.' + digits.slice(point) : '');
  if (text.includes('.')) text = text.replace(/0+$/, '').replace(/\.$/, '');
  return sign + text;
}
export function roundEven(value: number): number {
  const floor = Math.floor(value),
    fraction = value - floor;
  return fraction < 0.5
    ? floor
    : fraction > 0.5
      ? floor + 1
      : floor % 2 === 0
        ? floor
        : floor + 1;
}

// Never use browser-local date getters. Naive timestamps remain naive.
export function when(value: unknown): string {
  const match = string(value).match(
    /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d{1,9})?)?(Z|[+-]\d{2}:\d{2})?$/,
  );
  if (!match) throw new BadFormat();
  const [, y, mo, d, h, mi, seconds = '00', zone] = match;
  const date = new Date(`${y}-${mo}-${d}T${h}:${mi}:${seconds}Z`);
  if (
    !Number.isFinite(date.getTime()) ||
    Number(y) < 1 ||
    date.getUTCFullYear() !== Number(y) ||
    date.getUTCMonth() + 1 !== Number(mo) ||
    date.getUTCDate() !== Number(d) ||
    Number(h) > 23 ||
    Number(mi) > 59 ||
    Number(seconds) > 59
  )
    throw new BadFormat();
  if (!zone) return `${y}-${mo}-${d} ${h}:${mi}`;
  if (zone !== 'Z') {
    const hours = Number(zone.slice(1, 3)),
      minutes = Number(zone.slice(4));
    if (hours > 23 || minutes > 59) throw new BadFormat();
    date.setUTCMinutes(
      date.getUTCMinutes() -
        (zone[0] === '+' ? 1 : -1) * (hours * 60 + minutes),
    );
  }
  return date.toISOString().slice(0, 16).replace('T', ' ') + ' UTC';
}
const catalogKeys = [
  'course_code',
  'course_name',
  'description',
  'credits',
  'prereq_codes',
  'catalog_url',
  'snapshot_id',
  'imported_at',
  'retrieved_at',
];
function catalogSnapshot(value: unknown): {
  description: string | null;
  url: string;
  retrieved: string | null;
} | null {
  return guarded(() => {
    const c = object(value);
    if (Object.keys(c).some((key) => !catalogKeys.includes(key)))
      throw new BadFormat();
    const code = string(c.course_code)
      .trim()
      .toUpperCase()
      .match(/^([A-Z]{2,4})\s?(\d{4}[A-Z]?)$/);
    if (!code || !string(c.course_name).length) throw new BadFormat();
    const description = optionalString(c.description);
    if (description && Array.from(description).length > 20000)
      throw new BadFormat();
    integer(c.credits, 0, 12);
    strings(c.prereq_codes ?? []);
    string(c.snapshot_id);
    when(c.imported_at);
    const retrieved = c.retrieved_at == null ? null : when(c.retrieved_at);
    const url = string(c.catalog_url);
    if (
      url !==
      `https://catalog.northeastern.edu/course-descriptions/${code[1]!.toLowerCase()}/`
    )
      throw new BadFormat();
    return { description, url, retrieved };
  });
}
type Section = {
  status: 'not_listed' | 'parsed' | 'unparsed';
  rule: unknown;
  raw_text: unknown;
};
type DocumentView = {
  course_id: string;
  course_code: string;
  course_name: string;
  catalog_year: string;
  prerequisite: Section;
  corequisite: Section;
  credit: { kind: 'fixed' | 'range'; raw_text: string } | null;
};
type Listing = {
  available: boolean;
  documents: DocumentView[];
  unusable: number;
  warnings: string[];
};
function section(value: unknown): Section {
  const s = object(value);
  if (
    !['not_listed', 'parsed', 'unparsed'].includes(string(s.status)) ||
    !Object.hasOwn(s, 'rule')
  )
    throw new BadFormat();
  if (s.status === 'unparsed') string(s.raw_text);
  else optionalString(s.raw_text);
  return {
    status: s.status as Section['status'],
    rule: s.rule,
    raw_text: s.raw_text,
  };
}
function listing(value: unknown): Listing | null {
  return guarded(() => {
    const b = object(value);
    if (typeof b.schema_available !== 'boolean' || !Array.isArray(b.documents))
      throw new BadFormat();
    const documents = b.documents.map((value) => {
      const doc = object(value),
        req = object(doc.requisites);
      const year = string(doc.catalog_year);
      if (!/^\d{4}-\d{4}$/.test(year)) throw new BadFormat();
      let credit: DocumentView['credit'] = null;
      if (doc.credit_hours !== null) {
        const hours = object(doc.credit_hours);
        if (hours.kind !== 'fixed' && hours.kind !== 'range')
          throw new BadFormat();
        credit = { kind: hours.kind, raw_text: string(hours.raw_text) };
      }
      return {
        course_id: string(doc.course_id),
        course_code: string(doc.course_code),
        course_name: string(doc.course_name),
        catalog_year: year,
        prerequisite: section(req.prerequisite),
        corequisite: section(req.corequisite),
        credit,
      };
    });
    const unusable = integer(b.unusable_records, 0);
    if (unusable === null) throw new BadFormat();
    return {
      available: b.schema_available,
      documents,
      unusable,
      warnings: strings(b.warnings),
    };
  });
}
function ownDocuments(body: JsonObject, bundle: Listing) {
  return bundle.documents.filter(
    (d) =>
      d.course_id === body.course_id &&
      d.course_code === body.primary_code &&
      d.course_name === body.primary_name,
  );
}
export function deepEqual(left: unknown, right: unknown): boolean {
  const stack: [unknown, unknown][] = [[left, right]];
  while (stack.length) {
    const [a, b] = stack.pop()!;
    if (a === b) continue;
    if (Array.isArray(a) && Array.isArray(b)) {
      if (a.length !== b.length) return false;
      for (let i = 0; i < a.length; i++) stack.push([a[i], b[i]]);
    } else if (isObject(a) && isObject(b)) {
      const keys = Object.keys(a);
      if (
        keys.length !== Object.keys(b).length ||
        keys.some((key) => !Object.hasOwn(b, key))
      )
        return false;
      for (const key of keys) stack.push([a[key], b[key]]);
    } else return false;
  }
  return true;
}
function sameSection(a: Section, b: Section) {
  return (
    a.status === b.status &&
    deepEqual(a.rule, b.rule) &&
    (a.status !== 'unparsed' || a.raw_text === b.raw_text)
  );
}
export function requisiteSummary(body: JsonObject): string[] {
  if (body.course_requisites == null) return [NO_RULES];
  const bundle = listing(body.course_requisites);
  if (!bundle)
    return ['年度规则没有通过校验，暂不显示；不表示没有先修或共修要求。'];
  if (!bundle.available)
    return ['结构化先修规则暂时不可用；不表示没有先修或共修要求。'];
  const lines: string[] = [];
  if (
    bundle.unusable > 0 ||
    bundle.warnings.includes('structured_requisite_schema_unusable')
  )
    lines.push('存在不可用记录或存储结构；不能据此确认完整要求。');
  const own = ownDocuments(body, bundle);
  if (own.length !== bundle.documents.length)
    lines.push('有课程身份不符的年度记录，未用于比较。');
  if (!own.length) return [...lines, NO_RULES];
  if (new Set(own.map((d) => d.catalog_year)).size !== own.length)
    return [...lines, '同年度有冲突记录，未任取一份比较。'];
  lines.push(
    '已记录 Catalog 年份：' +
      own
        .map((d) => d.catalog_year)
        .sort()
        .reverse()
        .join('、'),
  );
  if (own.length === 1) lines.push('只记录了一个年度，不能跨年比较。');
  else {
    const first = own[0]!;
    const same = own
      .slice(1)
      .every(
        (d) =>
          sameSection(d.prerequisite, first.prerequisite) &&
          sameSection(d.corequisite, first.corequisite),
      );
    lines.push(
      same
        ? '这些年度已记录的条款结构相同。'
        : '这些年度已记录的条款不同，请按适用年度核对。',
    );
  }
  return [
    ...lines,
    '未列出或未解析的条款仍未知；不判断个人适用年度或能否注册。',
  ];
}
export function creditRangeNote(body: JsonObject): string | null {
  const bundle = listing(body.course_requisites);
  if (!bundle) return null;
  const own = ownDocuments(body, bundle);
  if (
    !own.length ||
    new Set(own.map((d) => d.catalog_year)).size !== own.length
  )
    return null;
  const newest = [...own].sort((a, b) =>
    b.catalog_year.localeCompare(a.catalog_year),
  )[0]!;
  return newest.credit?.kind === 'range'
    ? `${newest.catalog_year} 目录标题学分：${newest.credit.raw_text}；实际班次学分未声明。`
    : null;
}
const delivery: Readonly<Record<string, string>> = {
  in_person: '线下',
  online: '线上',
  hybrid: '混合',
  async: '异步',
};
export function courseHeader(body: JsonObject): CourseHeaderView | null {
  return guarded(() => {
    const identity = courseIdentity(body);
    if (!identity) throw new BadFormat();
    const term = optionalString(body.term),
      credits = integer(body.credits, 0, 12),
      mode = optionalString(body.delivery_mode);
    const metadata: { label: string; value: string }[] = [];
    if (term) metadata.push({ label: '学期', value: term });
    if (credits !== null)
      metadata.push({ label: '学分', value: String(credits) });
    if (mode)
      metadata.push({
        label: '授课方式',
        value: Object.hasOwn(delivery, mode)
          ? delivery[mode]!
          : mode.replaceAll('_', ' '),
      });
    return {
      identity,
      metadata,
      notice: noticeLine(warnings(body), [
        'catalog_metadata_conflict',
        'synthetic_record_not_real_course',
      ]),
      creditRange: creditRangeNote(body),
    };
  });
}
function catalogCell(body: JsonObject): DetailCell {
  const e = evidence(body);
  if (!e) return { lines: [main('目录存档情况没有记录。')] };
  const c = catalogSnapshot(e.catalog),
    lines: DisplayLine[] = [];
  if (c) {
    if (c.description) lines.push(main(c.description));
    lines.push({
      ...note('课程描述来自 NEU 官方课程目录 的存档副本，不是实时核对。'),
      catalogUrl: c.url,
    });
  } else
    lines.push(
      note(
        e.catalog != null
          ? '目录存档没有通过格式或来源校验，所以不显示描述和链接。'
          : '没有官方目录描述的存档。',
      ),
    );
  const excluded = [
    'catalog_source_unavailable',
    'requisites_differ_by_catalog_year',
    'requisite_clause_unparsed',
    'structured_requisites_unusable',
  ];
  const warn = noticeLine(
    warnings(body).filter((code) => !excluded.includes(code)),
  );
  if (warn) lines.push({ ...note(warn), notice: true });
  if (c) {
    if (!c.description) lines.push(main('目录存档没有描述记录。'));
    lines.push(main(`目录抓取：${c.retrieved ?? '没有记录'}。`));
  }
  return { lines };
}
export function softEstimates(body: JsonObject): DetailCell {
  const workload = number(body.workload_hours_per_week, 0),
    difficulty = number(body.difficulty_score, 1, 5);
  const bits: string[] = [];
  if (workload !== null) bits.push(`每周约 ${generalNumber(workload)} 小时`);
  if (difficulty !== null) bits.push(`难度 ${generalNumber(difficulty)}/5`);
  return {
    lines: [
      main(bits.join(' · ') || '没有记录'),
      note('来自学生评价的估计，不是官方信息；缺失不等于零或简单。'),
      ...notice(body, ['field_evidence_value_conflict']),
    ],
  };
}
export function gradingText(value: unknown): string {
  return (
    array(value)
      .map((value) => {
        const item = object(value),
          name = string(item.name),
          weight = number(item.weight, 0, 1);
        return weight === null ? name : `${name} ${roundEven(weight * 100)}%`;
      })
      .join(' · ') || '没有记录'
  );
}
const requirement: Readonly<Record<string, string>> = {
  core: '核心 · core',
  foundation: '基础 · foundation',
  elective_pool: '选修池 · elective',
  capstone: '毕业项目 · capstone',
};
function programs(body: JsonObject): DetailCell {
  const placements = array(body.program_context).map((value) => {
    const p = object(value),
      kind = string(p.requirement_type);
    string(p.program_id);
    const semester = integer(p.semester_recommended, 0);
    return {
      name: string(p.program_name),
      label: Object.hasOwn(requirement, kind) ? requirement[kind]! : kind,
      semester: semester === null ? null : `第 ${semester} 学期推荐`,
    };
  });
  return placements.length
    ? {
        programs: placements,
        lines: [
          note('旧 seed 关系，未核验；不是正式方案，不判断注册或毕业资格。'),
        ],
      }
    : { lines: [main('没有记录；不表示不属于任何方案。')] };
}
export function detailCell(row: DetailRow, body: JsonObject): DetailCell {
  const value = guarded(() => {
    switch (row) {
      case '官方目录描述':
        return catalogCell(body);
      case '学生评价里的估计':
        return softEstimates(body);
      case '先修／共修':
        return {
          lines: [
            ...requisiteSummary(body).map(main),
            note('在详情里看完整规则'),
          ],
        };
      case '主题': {
        const topics =
          body.topics_covered == null ? [] : strings(body.topics_covered);
        return {
          topics,
          lines: [
            ...(!topics.length ? [main('没有记录')] : []),
            ...notice(body, ['topics_source_unavailable']),
          ],
        };
      }
      case '考核构成':
        return { lines: [main(gradingText(body.grading_components))] };
      case '在培养方案里的位置':
        return programs(body);
      case '缺的数据': {
        const e = evidence(body);
        if (!e) return { lines: [main('缺失字段没有记录；不表示数据齐全。')] };
        const missing =
          e.missing_fields == null ? [] : strings(e.missing_fields);
        return {
          lines: [
            main(
              missing.length
                ? '缺失：' +
                    missing
                      .map((code) =>
                        Object.hasOwn(fieldLabels, code)
                          ? fieldLabels[code]
                          : code,
                      )
                      .join('、')
                : '没有列出缺失项；不表示数据齐全',
            ),
            note('缺失不等于零、简单或无要求。'),
          ],
        };
      }
    }
  });
  return value ?? { lines: [main(BAD_CELL)] };
}
export function failureMessage(status: number | null): string {
  if (status === 404) return '没有找到这门课。';
  if (status === null) return '暂时连不上服务，请稍后重新加载。';
  if (status === 429) return '请求过于频繁，请稍后重新加载。';
  if (status >= 500 && status < 600) return '服务暂时出错，请稍后重新加载。';
  return '加载没有完成，请稍后重新加载。';
}
export type ResolvedColumn =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; body: JsonObject; identity: Identity };
export function resolveColumn(
  column: CompareColumn | undefined,
): ResolvedColumn {
  if (!column || column.status === 'loading') return { status: 'loading' };
  if (column.status === 'error')
    return { status: 'error', message: failureMessage(column.httpStatus) };
  const identity = courseIdentity(column.body);
  return identity
    ? { status: 'ready', identity, body: column.body as JsonObject }
    : { status: 'error', message: '服务返回了无法识别的内容。' };
}
