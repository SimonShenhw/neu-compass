import { afterEach, expect, it, vi } from 'vitest';

// Vitest leaves __DEMO_ROUTES__ on globalThis, read when a module runs, so a module imported anew with it false is as
// a build has it (review B34). TopBar's lock and the shell's guest-badge exception go by the title and the address
// this gives, so with it false their demo entries can match nothing.
const scope = globalThis as Record<string, unknown>;
const inTests = scope.__DEMO_ROUTES__;
afterEach(() => {
  scope.__DEMO_ROUTES__ = inTests;
  vi.resetModules();
});

it('as a build has it, the demo addresses have no titles of their own, and the real pages keep theirs', async () => {
  expect(inTests).toBe(true);
  scope.__DEMO_ROUTES__ = false;
  vi.resetModules();
  const { pagePresentation } = await import('./routePresentation');
  for (const path of [
    '/compare-demo',
    '/coop-demo',
    '/privacy-demo',
    '/requisites-demo',
    '/course-detail-demo',
    '/search-demo',
    '/search-landing-demo',
    '/programs-demo',
    '/programs-draft-demo',
  ])
    expect(pagePresentation(path), path).toEqual({
      title: '找不到页面',
      navigationPath: undefined,
      isSearch: false,
    });
  expect(pagePresentation('/compare').title).toBe('课程对比');
  expect(pagePresentation('/privacy').title).toBe('数据与隐私');
  expect(pagePresentation('/course/CS-6140')).toEqual({
    title: '课程搜索',
    navigationPath: '/',
    isSearch: true,
  });
});
