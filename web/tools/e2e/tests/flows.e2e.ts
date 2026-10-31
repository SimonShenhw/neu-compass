import { expect } from '@playwright/test';
import { signIn, test } from './support';

// The site's main ways through, as the R6 walkthrough went them by hand, on the dev API's synthetic accounts (its fake
// Google page lists them). On the desktop only (playwright.config.ts): the phone's menu has a test of its own.

// The plan picker is named by its label and the plan chosen (src/components/Select.tsx, models/programFormat.ts).
const PLAN_LABEL = '选择目录版本与路径（不自动判定你的适用年度）';
const STANDARD_PLAN =
  'boston · Catalog 2026-2027 · 普通 MS · 共同部分／未限定 concentration';

test('signing in with the fake Google and out again: the sidebar says who, and focus goes back to the login', async ({
  page,
}) => {
  await page.goto('/');
  await signIn(page, 'Synthetic Student · husky.neu.edu');
  const sidebar = page.getByRole('complementary');
  await expect(sidebar).toContainText('Synthetic Student');
  await sidebar.getByRole('button', { name: '退出登录' }).click();
  const login = sidebar.getByRole('button', { name: '用 NEU 邮箱登录' });
  await expect(login).toBeFocused();
  await expect(sidebar).toContainText('已退出登录。');
});

test('a plan and a draft for it stay while a course page is open and after Back', async ({
  page,
}) => {
  await page.goto('/programs/cs-ms');
  const plan = page.getByRole('combobox', { name: PLAN_LABEL });
  await plan.click();
  await page.getByRole('option', { name: STANDARD_PLAN }).click();
  await expect(plan).toHaveAccessibleName(`${PLAN_LABEL} ${STANDARD_PLAN}`);
  await page.getByRole('textbox', { name: /^课号/ }).fill('CS 5800');
  await page.getByRole('button', { name: '加入草案' }).click();
  await expect(
    page.getByRole('button', { name: '移除 CS 5800' }),
  ).toBeVisible();
  await page.getByRole('button', { name: '查看 CS 5010' }).first().click();
  await expect(page).toHaveURL(/\/course\/CS-5010$/);
  // The address changes before the program page goes: Back only once the course page is drawn instead (review A35).
  await expect(page.getByRole('region', { name: '课程详情' })).toBeVisible();
  await expect(plan).toHaveCount(0);
  await page.goBack();
  await expect(page).toHaveURL(/\/programs\/cs-ms$/);
  await expect(plan).toHaveAccessibleName(`${PLAN_LABEL} ${STANDARD_PLAN}`);
  // The draft itself, not the last check's answer shown while it is checked again.
  await expect(page.getByText('正在核对课程…')).toHaveCount(0);
  await expect(
    page.getByRole('button', { name: '移除 CS 5800' }),
  ).toBeVisible();
});

test('two courses added from their pages are compared side by side', async ({
  page,
}) => {
  await page.goto('/course/CS-6140');
  await page.getByRole('button', { name: '加入对比' }).click();
  await page
    .getByRole('region', { name: '课程先修要求' })
    .getByRole('button', { name: '查看 CS 5800' })
    .click();
  await expect(page).toHaveURL(/\/course\/CS-5800$/);
  await page.getByRole('button', { name: '加入对比' }).click();
  await page
    .getByRole('navigation', { name: '主导航' })
    .getByRole('link', { name: /课程对比/ })
    .click();
  const compared = page.getByRole('region', { name: '课程对比内容' });
  await expect(compared.getByRole('table')).toBeVisible();
  await expect(
    compared.getByRole('button', { name: '移出 CS 6140' }),
  ).toBeVisible();
  await expect(
    compared.getByRole('button', { name: '移出 CS 5800' }),
  ).toBeVisible();
});

// A second account that nothing else uses: its upload goes with the account, so a run leaves the dev API as it found
// it for the next one.
test('a Co-op experience shared, then the account and the upload deleted', async ({
  page,
}) => {
  await page.goto('/');
  await signIn(page, 'Second Student · northeastern.edu');
  await page
    .getByRole('navigation', { name: '主导航' })
    .getByRole('link', { name: /Co-op 经验/ })
    .click();
  const form = page.getByRole('form', { name: '分享你的 Co-op 经验' });
  await form.getByLabel(/^公司/).fill('Example Co.');
  await form.getByLabel(/^职位/).fill('Data Co-op');
  await form.getByRole('button', { name: '提交经验' }).click();
  const shared = page.getByRole('status', { name: '投稿结果' });
  await expect(shared).toContainText('编号');
  await page
    .getByRole('navigation', { name: '主导航' })
    .getByRole('link', { name: /数据与隐私/ })
    .click();
  await page.getByRole('checkbox', { name: '我知道删除以后不能恢复' }).check();
  await page.getByRole('button', { name: '删除我的账号和投稿' }).click();
  const deleted = page.getByRole('status', { name: '删除结果' });
  await expect(deleted).toContainText('删除');
  await expect(
    page
      .getByRole('complementary')
      .getByRole('button', { name: '用 NEU 邮箱登录' }),
  ).toBeVisible();
});
