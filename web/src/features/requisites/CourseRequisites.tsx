import { useState } from 'react';
import type { RequisiteDocument, RequisiteSection } from '../../api/requisites';
import { Button } from '../../components/Button';
import {
  legacyLabelsAllowed,
  legacyPrerequisites,
  parseRequisites,
} from '../../models/requisites';
import { Disclosure, Line, PanelContext, PanelSelect } from './PanelPrimitives';
import { ProgramContextPanel } from './ProgramContextPanel';
import { RequisiteRulesTree } from './RequisiteRulesTree';
import { SourceEvidence } from './SourceEvidence';
import styles from './Requisites.module.css';

export interface CourseRequisitesProps {
  course: { course_id: string; primary_code: string; primary_name: string };
  requisites: unknown;
  prerequisites: unknown;
  onOpenCourse: (code: string) => void;
}
export const YEAR_LABEL = '先修规则的 Catalog 年份（不会默认选最新）';
export const YEAR_EMPTY = '请选择适用的年份';
export const INVALID =
  '结构化规则格式/来源/原文一致性校验未通过，未显示；不回退为旧资格图。';
export function CourseRequisites({
  course,
  requisites,
  prerequisites,
  onOpenCourse,
}: CourseRequisitesProps) {
  const parsed = parseRequisites(requisites);
  const listing = parsed.kind === 'ok' ? parsed.listing : null;
  const own =
    listing?.documents.filter(
      (d) =>
        d.course_id === course.course_id &&
        d.course_code === course.primary_code &&
        d.course_name === course.primary_name,
    ) ?? [];
  const conflict = new Set(own.map((d) => d.catalog_year)).size !== own.length;
  const available = listing?.schema_available && !conflict ? own : [];
  const [year, setYear] = useState<string | null>(() =>
    available.length === 1 ? available[0]!.catalog_year : null,
  );
  const selected = available.find((d) => d.catalog_year === year);
  if (year !== null && !selected) setYear(null);
  const rows = legacyPrerequisites(prerequisites);
  const labels = legacyLabelsAllowed(parsed);
  let rules;
  if (parsed.kind === 'absent')
    rules = (
      <Line kind="note">
        当前接口尚无结构化规则；旧关系只能作未核验导航参考。
      </Line>
    );
  else if (parsed.kind === 'invalid')
    rules = <Line kind="warning">{INVALID}</Line>;
  else if (!parsed.listing.schema_available)
    rules = (
      <Line kind="note">
        结构化先修存储尚不可用；需显式副本迁移，不在页面自动建表。
      </Line>
    );
  else
    rules = (
      <>
        {(parsed.listing.unusable_records > 0 ||
          parsed.listing.warnings.includes(
            'structured_requisite_schema_unusable',
          )) && (
          <Line kind="warning">
            存在无法使用的结构化记录或存储结构；未将它解释成没有要求，也不回退旧图。
          </Line>
        )}
        {parsed.listing.documents
          .filter((d) => !own.includes(d))
          .map((_, index) => (
            <Line key={index} kind="warning">
              一份结构化记录的课程身份不符，未显示。
            </Line>
          ))}
        {own.length === 0 ? (
          <Line kind="note">
            没有可用的年度规则；这不表示没有先修或共修要求。
          </Line>
        ) : conflict ? (
          <Line kind="warning">同年度有多份冲突规则，未任取第一份。</Line>
        ) : (
          <>
            <PanelSelect
              label={YEAR_LABEL}
              value={selected?.catalog_year ?? 'none'}
              onChange={(value) => setYear(value === 'none' ? null : value)}
              options={[
                { value: 'none', label: YEAR_EMPTY },
                ...own.map((d) => ({
                  value: d.catalog_year,
                  label: `Catalog ${d.catalog_year}（校区和个人路径未声明）`,
                })),
              ]}
            />
            {selected && (
              <>
                {own.length === 1 && (
                  <Line kind="note">
                    目前只记录了这一个 Catalog
                    年份，已默认显示；它不一定是你适用的年份。
                  </Line>
                )}
                <Sections document={selected} onOpenCourse={onOpenCourse} />
                <SourceEvidence document={selected} />
                <ProgramContextPanel
                  key={selected.catalog_year}
                  context={parsed.listing.program_contexts.find(
                    (c) =>
                      c.catalog_year === selected.catalog_year &&
                      c.course_code === course.primary_code,
                  )}
                />
              </>
            )}
          </>
        )}
      </>
    );
  return (
    <section className={styles.panel} aria-label="课程先修要求">
      <h2 data-kind="heading" data-part="requisites" data-depth="0">
        先修要求
      </h2>
      <Line kind="note">
        按目录原文整理，不判断你能不能注册；能否选课以学校系统为准。
      </Line>
      {rules}
      {rows.length > 0 && (
        <PanelContext value={{ part: 'legacy', depth: 0 }}>
          <Line kind="heading">
            {labels ? '旧平铺先修关系（未核验，仅供导航）' : '去看看这些先修课'}
          </Line>
          <Line kind="note">
            {labels
              ? '旧边不表达 AND/OR、最低成绩或共修；不能用它判断哪些课全部必修或能否注册。'
              : '只用来跳转；不表示「都要」还是「任选」、最低成绩或是否必修，以上面的先修规则为准。'}
          </Line>
          {rows.map((row, index) => {
            const text = labels
              ? row.primary_code && row.primary_name
                ? `${row.primary_code} — ${row.primary_name}`
                : row.course_id
              : [row.primary_code, row.primary_name]
                  .filter(Boolean)
                  .join(' · ') || row.course_id;
            const label = labels
              ? (new Map([
                  ['required', '必须先修'],
                  ['recommended', '建议先修'],
                  ['concurrent', '可同修'],
                ]).get(row.requirement) ?? row.requirement)
              : null;
            return (
              <div className={styles.legacy} key={index}>
                <div data-kind="legacy_row" data-part="legacy" data-depth="0">
                  <span
                    data-row-text
                    className={
                      labels && !(row.primary_code && row.primary_name)
                        ? styles.mono
                        : undefined
                    }
                  >
                    {labels ? (
                      row.primary_code && row.primary_name ? (
                        <>
                          <span data-row-code>{row.primary_code}</span>
                          {' — '}
                          <span data-row-name>{row.primary_name}</span>
                        </>
                      ) : (
                        <span data-row-id>{row.course_id}</span>
                      )
                    ) : (
                      text
                    )}
                  </span>
                  {label !== null && (
                    <span data-row-label className={styles.legacyLabel}>
                      {label}
                    </span>
                  )}
                </div>
                {row.primary_code !== null && (
                  <Button
                    size="sm"
                    data-kind="button"
                    data-part="legacy"
                    data-depth="0"
                    data-opens={row.primary_code}
                    onClick={() => onOpenCourse(row.primary_code!)}
                  >
                    查看
                  </Button>
                )}
              </div>
            );
          })}
        </PanelContext>
      )}
    </section>
  );
}
function Sections({
  document,
  onOpenCourse,
}: {
  document: RequisiteDocument;
  onOpenCourse: (code: string) => void;
}) {
  return (
    <>
      {(
        [
          ['先修课', document.requisites.prerequisite],
          ['共修课（与先修分开）', document.requisites.corequisite],
        ] as const
      ).map(([label, section]) => (
        <RequisitePart
          key={label}
          label={label}
          section={section}
          onOpenCourse={onOpenCourse}
        />
      ))}
    </>
  );
}
function RequisitePart({
  label,
  section,
  onOpenCourse,
}: {
  label: string;
  section: RequisiteSection;
  onOpenCourse: (code: string) => void;
}) {
  return (
    <>
      <Line kind="heading">{label}</Line>
      {section.status === 'not_listed' ? (
        <Line>课程块未列出这一段；不是已证明没有要求。</Line>
      ) : section.status === 'unparsed' ? (
        <>
          <Line>{`未解析：${section.reason}；保留整段，不展示部分成功树。`}</Line>
          <Line>{section.raw_text}</Line>
        </>
      ) : (
        <>
          <Line>完整段语法已解析；不代表要求已满足。</Line>
          <div
            data-kind="text"
            data-part="requisites"
            data-depth="0"
            data-rule-tree
          >
            <RequisiteRulesTree
              node={section.rule}
              onOpenCourse={onOpenCourse}
            />
          </div>
          <Disclosure label={`${label}原文（仅统一空白）`}>
            <Line>{section.raw_text}</Line>
          </Disclosure>
        </>
      )}
    </>
  );
}
