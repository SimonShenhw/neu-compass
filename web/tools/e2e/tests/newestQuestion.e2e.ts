import { expect } from '@playwright/test';
import {
  answer,
  answered,
  ask,
  askBox,
  atTheTop,
  box,
  countScrolls,
  landed,
  scrolls,
  test,
} from './support';

// R6, the user's choice of 10-29: a question asked comes into view at the top of the window, its answer below it. The
// last turn is at least a window high (the large viewport's, less the box; from the second turn plus the border and
// padding above the question), so it can reach the top (review A34, recheck 1 of round 34).

test('a question asked comes to the top of the window, its answer below it, the second as the first', async ({
  page,
}, { project }) => {
  await page.goto('/');
  await landed(page);
  await ask(page, 'CS 5800 讲什么？');
  await answered(page, 1);
  await atTheTop(page);
  await ask(page, 'CS 6140 呢？');
  await answered(page, 2);
  await atTheTop(page);
  const form = await box(askBox(page));
  const reply = await box(answer(page, 2));
  // The answer starts in view, and on the desktop all of it is above the box. On the phone the question and its answer
  // are taller than the window less the box (390×844: 58 and 620, the related course open in it, 444, and the follow-up
  // buttons, 96, against 655): the rest is a scroll away.
  expect(reply.top).toBeLessThan(form.top);
  if (project.name === 'desktop')
    expect(reply.bottom).toBeLessThanOrEqual(form.top + 1);
  // From the second turn the box sits on the window's bottom edge (recheck 1 of round 34: it was 4–5 px above).
  expect(
    Math.abs(form.bottom - (await page.evaluate(() => innerHeight))),
  ).toBeLessThanOrEqual(1);
});

// From a course page the question opens the search page with NEWEST_QUESTION, read once: the entry is replaced
// without it, not added to, so one Back is the course page and Forward does not bring the question into view again
// (reviews A34, B34; recheck 1). Where Forward leaves the page is the browser's: it puts back where the page was left,
// which was the question at the top (review A35), so only the page's own scrolls are counted.
test('a question asked on a course page is at the top of the search page; one Back is the course page, Forward scrolls nowhere', async ({
  page,
}) => {
  await countScrolls(page);
  await page.goto('/course/CS-6140');
  await expect(page.getByRole('region', { name: '课程详情' })).toBeVisible();
  const entries = await page.evaluate(() => history.length);
  await ask(page, 'CS 6140 讲什么？');
  await expect(page).toHaveURL(/127\.0\.0\.1:4173\/$/);
  await answered(page, 1);
  await atTheTop(page);
  expect(await page.evaluate(() => history.length)).toBe(entries + 1);
  expect(
    await page.evaluate(
      () => (history.state as { usr?: unknown } | null)?.usr ?? null,
    ),
  ).toBeNull();
  await page.goBack();
  await expect(page).toHaveURL(/\/course\/CS-6140$/);
  const before = (await scrolls(page)).length;
  await page.goForward();
  await expect(page).toHaveURL(/127\.0\.0\.1:4173\/$/);
  await expect(answer(page, 1)).toBeVisible();
  expect((await scrolls(page)).slice(before)).not.toContain('question');
});

test('coming back to the search page shows the conversation again and scrolls nowhere', async ({
  page,
}) => {
  await countScrolls(page);
  await page.goto('/');
  await landed(page);
  await ask(page, 'CS 5800 讲什么？');
  await answered(page, 1);
  await answer(page, 1).getByRole('button', { name: '查看 CS 5800' }).click();
  await expect(page).toHaveURL(/\/course\/CS-5800$/);
  const before = (await scrolls(page)).length;
  await page.getByRole('link', { name: '回到课程搜索' }).click();
  await expect(answer(page, 1)).toBeVisible();
  expect((await scrolls(page)).slice(before)).not.toContain('question');
  // Nor by any other means (review A35): two frames on, the page is where the shell put it, at its top.
  await page.evaluate(
    () =>
      new Promise((done) =>
        requestAnimationFrame(() => requestAnimationFrame(done)),
      ),
  );
  expect(await page.evaluate(() => scrollY)).toBe(0);
});
