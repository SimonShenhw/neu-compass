import { LoaderCircle, Search, X } from 'lucide-react';
import { useRef, useState } from 'react';
import type { CoopPageProps } from '../api/coop';
import { Button } from '../components/Button';
import { CoopCard } from '../components/CoopCard';
import { CoopForm } from '../components/CoopForm';
import { EmptyState } from '../components/EmptyState';
import { Select } from '../components/Select';
import { filterCoops, industryOptions } from '../models/coop';
import styles from './CoopPage.module.css';

function CoopList({
  list,
  onRetryList,
}: Pick<CoopPageProps, 'list' | 'onRetryList'>) {
  const [query, setQuery] = useState('');
  const [industry, setIndustry] = useState('all');
  const search = useRef<HTMLInputElement>(null);
  function clearFilters() {
    setQuery('');
    setIndustry('all');
    search.current?.focus();
  }
  if (list.status === 'loading')
    return (
      <p role="status" className={styles.state}>
        <LoaderCircle aria-hidden="true" />
        正在加载
      </p>
    );
  if (list.status === 'error')
    return (
      <div className={styles.state}>
        <p role="alert">Co-op 列表暂时加载不了，请稍后重试。</p>
        <Button onClick={() => onRetryList()}>重试</Button>
      </div>
    );
  if (!list.records.length)
    return (
      <EmptyState>还没有可以公开的 Co-op 经验，欢迎分享第一条。</EmptyState>
    );
  const records = filterCoops(list.records, query, industry);
  return (
    <>
      <form
        className={styles.filters}
        aria-label="Co-op 筛选"
        onSubmit={(event) => event.preventDefault()}
      >
        <label className={styles.search}>
          <Search aria-hidden="true" />
          <span className="visually-hidden">搜索公司或职位</span>
          <input
            ref={search}
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索公司或职位"
          />
        </label>
        <Select
          label="筛选行业"
          value={industry}
          onChange={setIndustry}
          options={industryOptions}
        />
        <Button variant="ghost" size="sm" onClick={clearFilters}>
          <X aria-hidden="true" />
          清除筛选
        </Button>
      </form>
      <p className={styles.count} role="status" aria-label="筛选结果">
        {records.length} 条记录
      </p>
      <div className={styles.records}>
        {records.length ? (
          records.map((record) => (
            <CoopCard record={record} key={record.coop_id} />
          ))
        ) : (
          <EmptyState
            action={<Button onClick={clearFilters}>查看全部记录</Button>}
          >
            没有匹配的 Co-op 经验。
          </EmptyState>
        )}
      </div>
    </>
  );
}
function CoopContent({
  viewer,
  list,
  onRetryList,
  onSubmit,
  onLogin,
}: CoopPageProps) {
  return (
    <div className={styles.page}>
      <header className={styles.intro}>
        <h2>NEU Co-op 经验</h2>
        <p>
          这里有整理好的示例记录，也有同学分享的 Co-op
          经验。同学的分享先人工去掉个人信息并审核，同一类经验至少有 2
          位不同的同学分享后才公开。你分享的经验公开后，可以解锁更多细节。
        </p>
      </header>
      <section className={styles.viewer} aria-label="查看权限">
        {viewer.kind === 'guest' ? (
          <>
            <p>
              你现在是游客：只能看到公开记录的公司、职位、行业、学期和时长。用
              NEU 邮箱登录并分享自己的经验，经验公开后能看到更多：1
              条看面试细节，2 条看薪资区间。
            </p>
            <Button onClick={() => onLogin()}>登录</Button>
          </>
        ) : (
          <p>
            已公开贡献：{viewer.contributionCount} 条 · 当前等级{' '}
            {Math.min(viewer.contributionCount, 2)}
          </p>
        )}
      </section>
      <div className={styles.columns}>
        <section
          aria-label="Co-op 经历列表"
          aria-busy={list.status === 'loading'}
        >
          <h2 className={styles.listTitle}>经历列表</h2>
          <CoopList list={list} onRetryList={onRetryList} />
        </section>
        <aside className={styles.aside} aria-label="分享经验">
          {viewer.kind === 'member' ? (
            <CoopForm onSubmit={onSubmit} onLogin={onLogin} />
          ) : (
            <section className={styles.explainer}>
              <h2>分享你的 Co-op 经验</h2>
              <p>用 NEU 邮箱登录后才能分享。</p>
              <Button variant="primary" onClick={() => onLogin()}>
                登录
              </Button>
            </section>
          )}
        </aside>
      </div>
    </div>
  );
}
// Becoming a guest or a member unmounts private drafts and open record details. The live page keys this by the
// session's owner as well (CoopRoute), so another person starts afresh; the same person's level going up after an
// upload keeps the upload's result on screen (R5d).
export function CoopPage(props: CoopPageProps) {
  return <CoopContent {...props} key={props.viewer.kind} />;
}
