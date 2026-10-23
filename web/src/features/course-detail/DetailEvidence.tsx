import type {
  DetailView,
  ParsedAnswerEvidence,
} from '../../models/courseDetail';
import {
  confidenceEven,
  evidenceValue,
  FIELD_LABELS,
  labelFor,
  noticeLine,
  OVERVIEW_EXCLUDED,
  snapshotDigest,
  sourceKind,
  sourceSummary,
  utcMinute,
  WARNING_LABELS,
} from '../../models/courseDetailFormat';
import { DetailDisclosure, DetailLink, DetailText } from './DetailPrimitives';

export function DetailOverview({
  evidence,
}: {
  evidence: ParsedAnswerEvidence | null;
}) {
  if (!evidence) return null;
  const { catalog } = evidence;
  const notice = noticeLine(evidence.warnings, OVERVIEW_EXCLUDED);
  return (
    <>
      {catalog.kind === 'ok' ? (
        <>
          {catalog.snapshot.description && (
            <DetailText>{catalog.snapshot.description}</DetailText>
          )}
          <DetailLink href={catalog.snapshot.catalog_url} overview>
            NEU 官方课程目录
          </DetailLink>
        </>
      ) : (
        <DetailText kind="note">
          {catalog.kind === 'invalid'
            ? '目录存档没有通过格式或来源校验，所以不显示描述和链接。'
            : '没有官方目录描述的存档。'}
        </DetailText>
      )}
      {notice && <DetailText kind="note">{notice}</DetailText>}
    </>
  );
}
function SnapshotDetails({ evidence }: { evidence: ParsedAnswerEvidence }) {
  const { catalog } = evidence;
  if (catalog.kind !== 'ok')
    return catalog.kind === 'invalid' ? (
      <DetailText kind="note">
        目录快照格式或来源校验未通过；未显示链接。
      </DetailText>
    ) : null;
  const s = catalog.snapshot,
    digest = snapshotDigest(s.snapshot_id);
  return (
    <>
      <DetailLink href={s.catalog_url}>官方目录来源</DetailLink>
      <DetailText
        kind="note"
        {...(digest ? { title: `完整快照 ID：${s.snapshot_id}` } : {})}
      >
        {`快照：${digest ? digest.slice(0, 12) + '…' : '格式异常'} · 导入：${utcMinute(s.imported_at)}`}
      </DetailText>
      <DetailText kind="note">{`抓取：${s.retrieved_at === null ? '未记录' : utcMinute(s.retrieved_at)}`}</DetailText>
    </>
  );
}
export function DetailEvidence({ body }: { body: DetailView }) {
  const e = body.answer_evidence;
  const sources = [...new Set(e?.source_review_ids ?? [])];
  return (
    <DetailDisclosure label="来源与说明（数据从哪来、缺了什么）">
      {e && (
        <>
          <DetailText kind="note">
            {e.catalog.kind === 'ok'
              ? '来源：已存目录快照（非实时核验）'
              : '来源：未附可追溯目录快照'}
          </DetailText>
          {e.missing_fields.length > 0 && (
            <DetailText kind="note">{`缺失：${e.missing_fields.map((field) => labelFor(FIELD_LABELS, field)).join('、')}；缺失不等于零/简单/无要求。`}</DetailText>
          )}
          {e.warnings.map((warning, index) => (
            <DetailText kind="note" key={index}>
              {labelFor(WARNING_LABELS, warning)}
            </DetailText>
          ))}
          <SnapshotDetails evidence={e} />
          {sources.length > 0 && (
            <>
              <DetailText kind="note">{`记录来源（非全文核验）：${sourceSummary(sources)}`}</DetailText>
              <DetailDisclosure label={`来源 ID（${sources.length}）`}>
                <DetailText>{sources.join('、')}</DetailText>
              </DetailDisclosure>
            </>
          )}
        </>
      )}
      {body.evidence_snippets.length > 0 && (
        <>
          <DetailText kind="heading">{`评价和大纲原文摘录（${body.evidence_snippets.length} 条）`}</DetailText>
          {body.evidence_snippets.map((s, index) => (
            <Quote key={index} snippet={s} />
          ))}
        </>
      )}
    </DetailDisclosure>
  );
}
function Quote({
  snippet: s,
}: {
  snippet: DetailView['evidence_snippets'][number];
}) {
  return (
    <>
      <DetailText kind="note">{`${labelFor(FIELD_LABELS, s.field)} · 抽取置信度 ${confidenceEven(s.confidence)}（不是事实概率）`}</DetailText>
      <DetailText>{`支持值：${evidenceValue(s.value)}\n来源：${sourceKind(s.source_id)} · ${s.source_id}\n引文：${s.quote}`}</DetailText>
    </>
  );
}
