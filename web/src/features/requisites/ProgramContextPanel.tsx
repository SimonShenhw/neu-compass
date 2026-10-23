import { useState } from 'react';
import type { ProgramContext } from '../../api/requisites';
import { planLabel, programRuleLines } from '../../models/requisiteRules';
import { Disclosure, Line, PanelSelect, SourceLink } from './PanelPrimitives';

export const PLAN_LABEL = '选择关联培养方案（不默认个人路径）';
export const PLAN_EMPTY = '请明确选择项目／校区／路径';
export function ProgramContextPanel({
  context,
}: {
  context: ProgramContext | undefined;
}) {
  const [planId, setPlanId] = useState<string | null>(null);
  const plans = context?.schema_available ? context.plans : [];
  const selected = plans.find((p) => p.plan_id === planId);
  // Drop removed IDs permanently; a later data refresh must not silently restore a personal choice.
  if (planId !== null && !selected) setPlanId(null);
  return (
    <Disclosure label="同一年份培养方案里的相关要求">
      <Line kind="heading">同年度培养方案上下文（与课程先修分开）</Line>
      <Line kind="note">
        仅关联显式列出本课程的已对照片段；开放前缀/编号范围不用于匹配。各方案条款不一定都约束本课，不代表你的适用路径。
      </Line>
      {!context || !context.schema_available ? (
        <Line kind="note">
          项目上下文未提供或存储尚不可用；不从旧 seed 猜条件。
        </Line>
      ) : (
        <>
          {(context.unusable_records > 0 ||
            context.warnings.includes('program_context_schema_unusable')) && (
            <Line kind="warning">
              存在同年度无法使用的方案记录或存储结构；不能据此断言没有更高门槛。
            </Line>
          )}
          {context.unreviewed_records > 0 && (
            <Line kind="note">
              有显式列课但尚未对照的方案，未作已核验上下文展示。
            </Line>
          )}
          {plans.length === 0 ? (
            <Line kind="note">
              没有可用的同年度显式关联；不是没有学校或项目政策，也不回退其他年度。
            </Line>
          ) : (
            <>
              <PanelSelect
                label={PLAN_LABEL}
                value={selected ? `plan:${selected.plan_id}` : 'none'}
                onChange={(value) =>
                  setPlanId(value === 'none' ? null : value.slice(5))
                }
                options={[
                  { value: 'none', label: PLAN_EMPTY },
                  ...plans.map((plan) => ({
                    value: `plan:${plan.plan_id}`,
                    label: planLabel(plan),
                  })),
                ]}
              />
              {selected && (
                <>
                  <Line>{planLabel(selected)}</Line>
                  <Line kind="note">{`${selected.coverage} · 来源片段已对照`}</Line>
                  <Line kind="note">
                    项目成绩/毕业/桥接条件与课程先修最低成绩的用途不同；不取较高值替换原文，不计算个人资格。Spring/Fall
                    入学适用性另核实。
                  </Line>
                  <Line>{selected.notes}</Line>
                  <Disclosure label="完整关联方案片段（保留分组、可选分支与未知）">
                    <Line>
                      {programRuleLines(selected.requirements).join('\n')}
                    </Line>
                  </Disclosure>
                  <SourceLink href={selected.source_url}>
                    官方培养方案来源
                  </SourceLink>
                  <Line kind="note">{`来源版次 ${selected.source_catalog_year} · 摘录 ${selected.captured_on} · 对照 ${selected.checked_on} · 不是实时查询`}</Line>
                  {selected.source_html_sha256 !== null && (
                    <Line>{`培养方案 HTML 字节摘要：${selected.source_html_sha256}`}</Line>
                  )}
                  <Disclosure label="方案来源摘录（非完整页面或政策）">
                    <Line>{selected.source_excerpt}</Line>
                  </Disclosure>
                </>
              )}
            </>
          )}
        </>
      )}
    </Disclosure>
  );
}
