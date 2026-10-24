import type { RequisiteDocument } from '../../api/requisites';
import { Disclosure, Line, SourceLink } from './PanelPrimitives';

const utc = (time: string) =>
  time.endsWith('Z') ? `${time.slice(0, -1)}+00:00` : time;
export function SourceEvidence({
  document: d,
}: {
  document: RequisiteDocument;
}) {
  const credit = d.credit_hours;
  const evidence = d.description_evidence;
  return (
    <Disclosure label="先修的来源与说明">
      <Line kind="note">
        展示课程块条款和未解释的描述证据；不判断个人注册、减免、成绩、开课或完整政策。旧平铺边不表达
        AND/OR/成绩。
      </Line>
      <Line kind="note">{`Catalog ${d.catalog_year} · 院系页面未声明校区或个人路径 · 不是完整政策`}</Line>
      <Line kind="heading">目录标题学分（独立来源证据）</Line>
      {credit === null ? (
        <Line>旧文档未捕获标题学分证据；不从旧整数 credits 补猜范围。</Line>
      ) : (
        <>
          <Line>{`原标题学分：${credit.raw_text}`}</Line>
          {credit.kind === 'range' ? (
            <>
              <Line>{`目录范围：${credit.minimum}–${credit.maximum}；实际班次学分未声明，不取端点或平均值作为固定学分。`}</Line>
              <Line kind="note">
                旧详情若有整数，也不是此范围已选定班次学分的证据。
              </Line>
            </>
          ) : (
            <Line>{`目录固定值：${credit.minimum}；不是当期班次或个人学位计入的确认。`}</Line>
          )}
          <Line kind="note">
            此证据不重写 Course 的整数
            credits，不用于范围筛选、学分求和或资格判断。
          </Line>
        </>
      )}
      <Line kind="heading">描述中的批准／资格关键词证据（未解释为规则）</Line>
      {evidence === null ? (
        <Line>旧文档未捕获描述证据；不是没有批准或资格条件。</Line>
      ) : (
        <>
          <Line>
            {evidence.status === 'not_listed'
              ? '课程块未列出 description 段；条件仍未知。'
              : evidence.status === 'no_keyword_match'
                ? '记录的描述未匹配当前有限关键词；不是已证明没有资格条件。'
                : '关键词候选待人工复核：可能为可选许可、否定或教学内容；不表示强制条件、已获批准或可注册。'}
          </Line>
          {evidence.status === 'review_needed' &&
            evidence.candidates.map((candidate, index) => (
              <Candidate
                key={index}
                label={`描述段 ${candidate.paragraph_index + 1} · 关键词：${candidate.markers.join(', ')}`}
                paragraph={evidence.paragraphs[candidate.paragraph_index]!}
              />
            ))}
          {evidence.paragraphs.length > 0 && (
            <Disclosure label="已记录的完整描述（逐段，仅统一空白）">
              {evidence.paragraphs.map((paragraph, index) => (
                <Line key={index}>{paragraph}</Line>
              ))}
            </Disclosure>
          )}
        </>
      )}
      <SourceLink href={d.source.url}>官方院系来源</SourceLink>
      <Line kind="note">{`来源捕获 UTC ${utc(d.source.captured_at)} · 导入 UTC ${utc(d.imported_at)}；不是实时查询`}</Line>
      <Line>{`来源 HTML 字节摘要：${d.source.sha256}（不证明不可篡改真实性或个人适用性）`}</Line>
      <Line kind="note">
        批准/资格证据和项目片段不是完整学校政策；个人成绩与适用性仍需核实。对话回答最多引用最近
        3
        个已记录年份的这些规则（更早的只计数）；在对话里选了方案、且方案那一年有记录时，只引用那一年。都不判断你能否注册，也不用于生成学期安排。
      </Line>
    </Disclosure>
  );
}
function Candidate({ label, paragraph }: { label: string; paragraph: string }) {
  return (
    <>
      <Line>{label}</Line>
      <Line>{paragraph}</Line>
    </>
  );
}
