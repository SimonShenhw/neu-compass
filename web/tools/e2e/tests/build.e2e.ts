import { expect } from '@playwright/test';
import { securityHeaders } from '../../../deploy/securityHeaders';
import { API, WEB, answered, ask, landed, test } from './support';

// What a build is, beyond what Vitest sees of its configuration (R6): no demo page, a skip link that moves focus
// without a history entry, and no request to anything but the site and its API (which every test checks too,
// tests/support.ts); the security headers of its build, under which every test runs (R7). On the desktop only
// (playwright.config.ts).

// R7: the preview sends what the build wrote (vite.config.ts), the headers nginx sends in production for its API, so
// every test's page runs under the production policy, the API aside.
test('the preview sends its build’s security headers on a page and on a deep link', async ({
  page,
}) => {
  for (const path of ['/', '/course/CS-6140']) {
    const headers = (await page.goto(path))?.headers() ?? {};
    for (const [name, value] of Object.entries(securityHeaders(API)))
      expect(headers[name.toLowerCase()], `${path}: ${name}`).toBe(value);
  }
});

// The policy is enforced, not only sent, and a refusal reaches every test's check (tests/support.ts): a script the page
// adds inline does not run, and its report arrives.
test('an inline script is refused, and the refusal is reported', async ({
  page,
  cspViolations,
}) => {
  await page.goto('/');
  await landed(page);
  const ran = await page.evaluate(() => {
    const script = document.createElement('script');
    script.textContent = 'document.body.dataset.inlineRan = "yes";';
    document.body.append(script);
    return document.body.dataset.inlineRan === 'yes';
  });
  expect(ran).toBe(false);
  await expect.poll(() => cspViolations.length).toBe(1);
  expect(cspViolations[0]).toMatch(/^script-src-elem refused inline/);
  // Made on purpose: not a failure of this test.
  cspViolations.length = 0;
});

// The nine demo routes of src/demoRoutes.tsx, which no build carries.
const DEMOS = [
  '/compare-demo',
  '/coop-demo',
  '/privacy-demo',
  '/requisites-demo',
  '/course-detail-demo',
  '/search-demo',
  '/programs-demo',
  '/programs-draft-demo',
  '/search-landing-demo',
];

test('no demo page in the build: each demo address is the not-found page', async ({
  page,
}) => {
  for (const path of DEMOS) {
    await page.goto(path);
    await expect(page.getByText('404 · 找不到这个页面'), path).toBeVisible();
    await expect(page).toHaveTitle(/^找不到页面/);
  }
});

// Not an in-page link any more: under the router an anchor added a history entry with no state, which dropped a plan
// link being checked (change log section 39's known item). A page opens with focus on main (AppShell), so the first
// Tab goes on into main, not back to the link: focus is put on the link itself, as Shift+Tab from the sidebar would.
test('the skip link moves focus to main, and the address and history stay as they were', async ({
  page,
}) => {
  await page.goto('/programs');
  await expect(
    page.getByRole('region', { name: '培养方案列表' }),
  ).toBeVisible();
  const entries = await page.evaluate(() => history.length);
  const skip = page.getByRole('link', { name: '跳到主要内容' });
  await skip.focus();
  await expect(skip).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.locator('#main-content')).toBeFocused();
  expect(page.url()).toBe(`${WEB}/programs`);
  expect(await page.evaluate(() => history.length)).toBe(entries);
});

// The fonts are bundled, the icons inline: a page asks nothing of a third party, not even a font host. Every page
// once, as a guest, asking the site and the API both.
test('the pages ask nothing of anyone but the site and its API', async ({
  page,
}) => {
  const origins = new Set<string>();
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (url.protocol === 'http:' || url.protocol === 'https:')
      origins.add(url.origin);
  });
  await page.goto('/');
  await landed(page);
  await ask(page, 'CS 5800 讲什么？');
  await answered(page, 1);
  for (const [path, region] of [
    ['/course/CS-6140', '课程详情'],
    ['/programs', '培养方案列表'],
    ['/programs/cs-ms', '项目课程表'],
    ['/compare', '课程对比内容'],
    ['/coop', 'Co-op 经历列表'],
  ] as const) {
    await page.goto(path);
    await expect(page.getByRole('region', { name: region })).toBeVisible();
  }
  await page.goto('/privacy');
  await expect(page.getByRole('heading', { name: '数据与隐私' })).toBeVisible();
  expect([...origins].sort()).toEqual([API, WEB].sort());
});
