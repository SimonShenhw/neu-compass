import { expect, test } from '@playwright/test';
import {
  answered,
  ask,
  conversation,
  field,
  landed,
  sendButton,
} from './support';

// Focus after a question (R3d spec 3, the focus rule of 10-25, R6): a question asked in the ask box leaves focus in its
// field, the first as those after it, whether sent with Enter or the send button, which the empty box disables (the
// browser took focus from it to the body; recheck 1 of round 34). A sample question's or a follow-up's button goes
// with the landing or its turn, so the conversation takes focus from it, however it was pressed.

test('a question sent with Enter, the send button clicked or pressed with the keyboard, leaves focus in the field', async ({
  page,
}) => {
  await page.goto('/');
  await landed(page);
  await ask(page, 'CS 5800 讲什么？');
  await answered(page, 1);
  await expect(field(page)).toBeFocused();
  await field(page).fill('CS 6140 呢？');
  await sendButton(page).click();
  await answered(page, 2);
  await expect(field(page)).toBeFocused();
  await field(page).fill('CS 5200 呢？');
  await page.keyboard.press('Tab');
  await expect(sendButton(page)).toBeFocused();
  await page.keyboard.press('Space');
  await answered(page, 3);
  await expect(field(page)).toBeFocused();
});

test('a sample question and a follow-up, clicked or pressed with the keyboard, give focus to the conversation', async ({
  page,
}) => {
  await page.goto('/');
  await landed(page);
  await page.getByRole('button', { name: 'CS 5800', exact: true }).click();
  await answered(page, 1);
  await expect(conversation(page)).toBeFocused();
  await page.getByRole('button', { name: '这门课讲什么内容？' }).focus();
  await page.keyboard.press('Enter');
  await answered(page, 2);
  await expect(conversation(page)).toBeFocused();
  await page.reload();
  await landed(page);
  await page.getByRole('button', { name: 'CS 5800', exact: true }).focus();
  await page.keyboard.press('Enter');
  await answered(page, 1);
  await expect(conversation(page)).toBeFocused();
});

// A click that leaves focus where it was, as Safari's does, or a screen reader pressing the button without focus on
// it (recheck 1 of round 34): the button is pressed while focus is on main.
test('pressed without focus on it, a sample question or a follow-up still gives focus to the conversation', async ({
  page,
}) => {
  await page.goto('/');
  await landed(page);
  await page.locator('#main-content').focus();
  await page
    .getByRole('button', { name: 'CS 5800', exact: true })
    .evaluate((button: HTMLElement) => button.click());
  await answered(page, 1);
  await expect(conversation(page)).toBeFocused();
  await page.locator('#main-content').focus();
  await page
    .getByRole('button', { name: '这门课作业量大吗？' })
    .evaluate((button: HTMLElement) => button.click());
  await answered(page, 2);
  await expect(conversation(page)).toBeFocused();
  // A question asked in the box after them stays there.
  await ask(page, 'CS 6140 呢？');
  await answered(page, 3);
  await expect(field(page)).toBeFocused();
});

test('after a question asked on a course page, focus is on the search page’s main', async ({
  page,
}) => {
  await page.goto('/course/CS-6140');
  await expect(page.getByRole('region', { name: '课程详情' })).toBeVisible();
  await ask(page, 'CS 6140 讲什么？');
  await answered(page, 1);
  await expect(page.locator('#main-content')).toBeFocused();
});
