import { matchPath } from 'react-router-dom';

const searchPage = { path: '/', title: '课程搜索' };
const pages = [
  searchPage,
  { path: '/compare', title: '课程对比' },
  { path: '/programs', title: '培养方案' },
  { path: '/coop', title: 'Co-op 经验' },
  { path: '/privacy', title: '数据与隐私' },
  { path: '/requisites-demo', title: '先修要求演示' },
  { path: '/course-detail-demo', title: '课程详情演示' },
];

export function pagePresentation(pathname: string) {
  // Match the router's case/trailing-slash rules, without rewriting the URL.
  const page =
    pages.find(({ path }) => matchPath(path, pathname)) ??
    (matchPath('/course/:code', pathname) ? searchPage : undefined);
  return {
    title: page?.title ?? '找不到页面',
    navigationPath: page?.path,
    isSearch: page?.path === '/',
  };
}
