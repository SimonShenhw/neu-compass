import { useState } from 'react';
import type { ReactNode } from 'react';
import { Button } from '../../components/Button';
import { CourseCode } from '../../components/CourseCode';
import {
  COMPACT_WARNINGS,
  requisiteYearsLine,
  scorePercent,
  scoreText,
} from '../../models/chatMeta';
import type { ParsedMeta, ParsedResult } from '../../models/chatMeta';
import {
  FIELD_LABELS,
  labelFor,
  oneLine,
} from '../../models/courseDetailFormat';
import { noticeLine } from '../../models/compare';
import { parsePlanContext, placementText } from '../../models/planContext';
import styles from './SearchConversation.module.css';

export function SearchText({
  children,
  kind = 'note',
}: {
  children: ReactNode;
  kind?: 'note' | 'text' | 'notice' | 'stream_error' | 'failure';
}) {
  return (
    <p
      data-kind={kind}
      className={
        kind === 'failure' || kind === 'stream_error'
          ? styles.warning
          : styles[kind]
      }
    >
      {children}
    </p>
  );
}
export function SearchDisclosure({
  label,
  children,
  defaultOpen = false,
}: {
  label: string;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <details
      className={styles.disclosure}
      open={open}
      onToggle={(e) => setOpen(e.currentTarget.open)}
    >
      <summary data-kind="disclosure">{label}</summary>
      <div className={styles.detailsBody}>{children}</div>
    </details>
  );
}
export function CompactEvidence({ result }: { result: ParsedResult }) {
  const e = result.evidence;
  if (!e) return null;
  const years = requisiteYearsLine(result.requisites),
    warning = noticeLine(e.warnings, COMPACT_WARNINGS);
  return (
    <>
      <SearchText>
        {e.catalog.kind === 'ok'
          ? '来源：已存目录快照（非实时核验）'
          : '来源：未附可追溯目录快照'}
      </SearchText>
      {years && <SearchText>{years}</SearchText>}
      {e.missing_fields.length > 0 && (
        <SearchText>{`缺失：${e.missing_fields
          .slice(0, 5)
          .map((x) => labelFor(FIELD_LABELS, x))
          .join(
            '、',
          )}${e.missing_fields.length > 5 ? `等 ${e.missing_fields.length} 项（详情查看全部）` : ''}；缺失不等于零/简单/无要求。`}</SearchText>
      )}
      {warning && <SearchText>{warning}</SearchText>}
    </>
  );
}
const matched = new Map([
  ['alias', '按课程代码找到'],
  ['hybrid', '按内容检索'],
  ['program', '按培养方案'],
  ['context', '接着上一个问题'],
  ['rejected', '没找到匹配的课'],
  ['empty', '没有结果'],
]);
type ValidMeta = Extract<ParsedMeta, { kind: 'ok' }>;
export function RelatedCourses({
  meta,
  onViewCourse,
}: {
  meta: ValidMeta;
  onViewCourse: (id: string) => void;
}) {
  if (!meta.results.length) return null;
  const top = meta.results.reduce(
    (max, r) => Math.max(max, r.score),
    -Infinity,
  );
  return (
    <SearchDisclosure
      label={`相关课程（${meta.results.length} 门）`}
      defaultOpen={meta.results.length <= 3}
    >
      <span data-kind="badge" className={styles.badge}>
        {matched.get(meta.matched_via) ?? '没有结果'}
      </span>
      {meta.results.map((r, index) => (
        <section
          className={styles.resultCard}
          key={index}
          aria-label={`相关课程 ${index + 1}`}
        >
          <div data-kind="result" className={styles.result}>
            <span data-rank className={styles.rank}>
              {index + 1}
            </span>
            <span data-code>
              <CourseCode>{oneLine(r.primary_code)}</CourseCode>
            </span>
            <strong data-name>{oneLine(r.primary_name)}</strong>
            <span data-score className={styles.score}>
              {scoreText(r.score)}
            </span>
            <div className={styles.track} aria-hidden="true">
              <div
                data-score-bar
                className={styles.fill}
                style={{ width: `${scorePercent(r.score, top)}%` }}
              />
            </div>
          </div>
          <CompactEvidence result={r} />
          <Button
            size="sm"
            data-kind="button"
            data-course-id={r.course_id}
            aria-label={`查看 ${oneLine(r.primary_code)}`}
            onClick={() => onViewCourse(r.course_id)}
          >
            查看
          </Button>
        </section>
      ))}
    </SearchDisclosure>
  );
}
export function PlanPosition({ meta }: { meta: ValidMeta }) {
  const plan = parsePlanContext(
    meta.plan_context,
    meta.results.map((r) => r.course_id),
  );
  if (!plan) return null;
  const byId = new Map(meta.results.map((r) => [r.course_id, r.primary_code]));
  const path = { standard: '普通 MS', align: 'Align', bridge: 'Bridge' }[
    plan.pathway
  ];
  return (
    <SearchDisclosure label="所选方案与课程位置">
      <SearchText>{`本回答按方案：${plan.program_id} · ${plan.campus} · Catalog ${plan.catalog_year} · ${path} · ${plan.concentration ?? '共同部分／未限定 concentration'}`}</SearchText>
      <SearchText>
        这是明确选择的方案文档，不代表你的适用年度、注册或毕业资格；未列出课程不代表禁止，开放池仍需核实。
      </SearchText>
      {plan.coverage === 'partial' && (
        <SearchText>
          仅部分规则；未建模内容未知，条件没有自动判定，跨组重叠不代表可以重复计入。
        </SearchText>
      )}
      {Object.entries(plan.placements).map(([id, entries], index) => {
        const code = byId.get(id) || `课程 ${index + 1}`;
        return (
          <div key={id} className={styles.placement}>
            {entries.length === 0 && (
              <SearchText kind="text">{`${code}：方案里没有写到这门课；不代表不能算，也不代表能算，请向项目核实。`}</SearchText>
            )}
            {entries.map((p, n) => (
              <SearchText
                kind="text"
                key={n}
              >{`${code}：${placementText(p)}`}</SearchText>
            ))}
            {plan.placements_omitted[id]! > 0 && (
              <SearchText kind="text">{`另有 ${plan.placements_omitted[id]} 处位置未列出，请到培养方案页核对完整规则。`}</SearchText>
            )}
          </div>
        );
      })}
      <a
        data-kind="link"
        href={plan.source_url}
        target="_blank"
        rel="noopener noreferrer"
      >
        方案官方目录来源
      </a>
      <SearchText>{`来源 Catalog ${plan.source_catalog_year} · 摘录 ${plan.captured_on} · 对照 ${plan.checked_on}；非实时核验`}</SearchText>
    </SearchDisclosure>
  );
}
