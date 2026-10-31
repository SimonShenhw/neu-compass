import AxeBuilder from '@axe-core/playwright';
import { expect } from '@playwright/test';
import type { Page } from '@playwright/test';
import { answered, ask, landed, optIn, signIn, test } from './support';

// axe on whole pages in a real browser, colour contrast included, which jsdom cannot compute (R6_PLAN section 1 item
// 7). Every rule axe runs by default, in both window sizes.

async function violations(page: Page) {
  const { violations } = await new AxeBuilder({ page }).analyze();
  return violations.map(({ id, impact, nodes }) => ({
    id,
    impact,
    targets: nodes.map(({ target }) => target.join(' ')),
  }));
}

for (const [path, region] of [
  ['/', '搜索落地内容'],
  ['/course/CS-6140', '课程详情'],
  ['/programs', '培养方案列表'],
  ['/programs/cs-ms', '项目课程表'],
  ['/compare', '课程对比内容'],
  ['/coop', 'Co-op 经历列表'],
] as const)
  test(`axe finds nothing on ${path}`, async ({ page }) => {
    await page.goto(path);
    await expect(page.getByRole('region', { name: region })).toBeVisible();
    expect(await violations(page)).toEqual([]);
  });

test('axe finds nothing on /privacy', async ({ page }) => {
  await page.goto('/privacy');
  await expect(
    page.getByRole('region', { name: '数据与隐私内容' }),
  ).toBeVisible();
  expect(await violations(page)).toEqual([]);
});

// Signed in, the page ends with the deletion of the account, which a guest does not see. The account is the one the
// sign-in flow uses; nothing is deleted. On the desktop: the phone has the sidebar's login behind its menu.
test('axe finds nothing on /privacy signed in, the deletion at its end', async ({
  page,
}, { project }) => {
  test.skip(project.name !== 'desktop', 'the login is in the sidebar');
  await page.goto('/');
  await signIn(page, 'Synthetic Student · husky.neu.edu');
  await page
    .getByRole('navigation', { name: '主导航' })
    .getByRole('link', { name: /数据与隐私/ })
    .click();
  await expect(
    page.getByRole('checkbox', { name: '我知道删除以后不能恢复' }),
  ).toBeVisible();
  expect(await violations(page)).toEqual([]);
});

// Two answers with their votes: the votes and the courses of each answer are groups in its turn's region, not
// landmarks of their own by the same names (axe's landmark-unique).
test('axe finds nothing in a conversation of two saved answers with their votes', async ({
  page,
}) => {
  await page.goto('/');
  await landed(page);
  await optIn(page).check();
  await ask(page, 'CS 5800 讲什么？');
  await answered(page, 1);
  await ask(page, 'CS 6140 呢？');
  await answered(page, 2);
  // Both answers' votes, which come once each receipt is checked, after the answer (review B35), and their courses.
  await expect(page.getByRole('group', { name: '回答反馈' })).toHaveCount(2);
  await expect(page.getByRole('group', { name: '相关课程 1' })).toHaveCount(2);
  expect(await violations(page)).toEqual([]);
});
