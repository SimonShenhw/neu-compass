import type { Load } from '../../api/load';
import type { ProgramPlanDoc, ProgramPolicyView } from '../../api/programs';
import { hash, scopeKey } from '../../models/programGuard';
import { parsePolicyView } from '../../models/programPolicy';
import { capturedText } from '../../models/programFormat';
import { Disclosure, Line, SourceLink } from './ProgramParts';
import styles from './Programs.module.css';

const colleges = {
  khoury: 'Khoury College of Computer Sciences',
  camd: 'College of Arts, Media and Design',
  engineering: 'College of Engineering',
};
const statusText: Record<
  Exclude<ProgramPolicyView['status'], 'ready'>,
  string
> = {
  not_linked: '该精确方案尚无政策证据关联；不能套用其他年度、方向或路径。',
  draft: '该方案尚未完成来源对照，未显示关联政策证据。',
  stale: '方案范围或内容版本已变化，政策关联须重新核对；未显示旧证据。',
  unavailable: '政策文件或来源存档不可用；未重新抓取或回退到旧课程表。',
  unusable: '政策证据或来源一致性校验未通过；未显示不完整的可信片段。',
};
export function ProgramPolicies({
  plan,
  revision,
  policies,
}: {
  plan: ProgramPlanDoc;
  revision: string | undefined;
  policies: Load | null;
}) {
  if (!policies || policies.status === 'loading')
    return <p role="status">正在加载政策证据…</p>;
  if (policies.status === 'failed')
    return (
      <Line kind="note">
        无法加载所选方案的政策证据；未使用旧缓存，方案规则仍可浏览。
      </Line>
    );
  const parsed = parsePolicyView(policies.data);
  if (parsed.kind === 'invalid')
    return (
      <Line kind="note">政策响应格式／来源字段校验未通过，未显示证据。</Line>
    );
  const view = parsed.view;
  if (
    view.plan_id !== plan.plan_id ||
    scopeKey(view.scope) !== scopeKey(plan) ||
    !hash(revision) ||
    view.plan_content_sha256 !== revision
  )
    return (
      <Line kind="note">
        政策响应与当前所选方案的范围／内容版本不一致；请刷新方案后重试，未显示旧证据。
      </Line>
    );
  if (view.status !== 'ready')
    return <Line kind="note">{statusText[view.status]}</Line>;
  if (
    plan.review_status !== 'source_checked' ||
    !plan.checked_on ||
    !view.checked_on ||
    view.checked_on < plan.checked_on
  )
    return (
      <Line kind="note">方案来源对照或审核版本已变化，未显示旧政策证据。</Line>
    );
  return (
    <section className={styles.policy} aria-label="学校与学院政策证据">
      <Line kind="note">
        学校／学院政策证据：仅选定片段，不是完整政策或个人资格审核；不合并不同用途的成绩／学分条件。
      </Line>
      <Line>{`Home college（项目页关联，不按课程前缀猜）：${colleges[view.link!.home_college]}`}</Line>
      <Line>{`政策对照记录：${view.checked_by} · ${view.checked_on}`}</Line>
      <Line kind="note">
        SHA
        核对只证明本地输入一致，不证明来源真实、摘要语义正确或你的个人适用年度。
      </Line>
      {view.policies.map((p) => (
        <section key={p.policy_id} className={styles.policyItem}>
          <h3 data-kind="text">{`${p.authority === 'university' ? '学校通用' : colleges[p.authority]} · ${p.source.page_title}`}</h3>
          <SourceLink href={p.source.url}>官方政策来源</SourceLink>
          <Line kind="note">{`Catalog ${p.source.catalog_year} · 捕获 ${capturedText(p.source.captured_at)} · 选定片段`}</Line>
          <Line>{`政策 HTML 字节摘要：${p.source.sha256}`}</Line>
          {p.fragments.map((f) => {
            const list = f.source_kind === 'list';
            const label = list ? '列表块' : '段落';
            return (
              <div key={f.fragment_id} className={styles.fragment}>
                <Line>{`摘要：${f.summary}`}</Line>
                <Line>{`限制／未知：${f.limitation}`}</Line>
                <Disclosure
                  title={`政策原文片段 · ${p.policy_id} · ${list ? 'l' : 'p'}${f.paragraph_index}`}
                >
                  <Line>{`正文零基${label} ${f.paragraph_index} · 标题：${f.heading ?? '无小节标题'}`}</Line>
                  <Line>{f.source_paragraph}</Line>
                  <Line>{`${label}文字摘要：${f.paragraph_sha256}`}</Line>
                </Disclosure>
              </div>
            );
          })}
        </section>
      ))}
    </section>
  );
}
