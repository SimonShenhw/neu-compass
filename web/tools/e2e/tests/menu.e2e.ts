import { expect, test } from '@playwright/test';
import { landed } from './support';

// The phone's navigation menu (the sidebar in a dialog): focus goes into it, it carries the footer's two sentences
// (R6), and Escape gives focus back to the button that opened it.
test('the menu opens with focus in it and the footer, and Escape gives focus back to its button', async ({
  page,
}) => {
  await page.goto('/');
  await landed(page);
  const open = page.getByRole('button', { name: '打开导航菜单' });
  await open.click();
  const menu = page.getByRole('dialog');
  await expect(menu).toBeVisible();
  await expect(menu).toContainText('课程数据可能滞后');
  await expect(menu).toContainText('非商业 / F1');
  expect(
    await menu.evaluate((dialog) => dialog.contains(document.activeElement)),
  ).toBe(true);
  await page.keyboard.press('Escape');
  await expect(menu).toBeHidden();
  await expect(open).toBeFocused();
});
