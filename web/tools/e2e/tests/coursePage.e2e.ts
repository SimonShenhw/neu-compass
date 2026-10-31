import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import { box } from './support';

// R6, the user's choice of 10-29: below 1200 wide the course page shows the course first, and a screen reader reads it
// first; from 1200 wide the grid puts the conversation back on the left (SearchPage.module.css), which jsdom cannot
// lay out.

async function opened(page: Page) {
  await page.goto('/course/CS-6140');
  await expect(page.getByRole('region', { name: '课程详情' })).toBeVisible();
  return {
    course: page.getByRole('group', { name: 'CS 6140' }),
    questions: page.getByRole('region', { name: '课程问答' }),
  };
}

for (const width of [768, 1024] as const)
  test(`${width} wide: the course comes first, in the page and in its order`, async ({
    page,
  }, { project }) => {
    test.skip(project.name !== 'desktop', 'one run of each size');
    await page.setViewportSize({ width, height: 900 });
    const { course, questions } = await opened(page);
    expect(
      await course.evaluate(
        (panel, other) =>
          Boolean(
            other &&
            panel.compareDocumentPosition(other) &
              Node.DOCUMENT_POSITION_FOLLOWING,
          ),
        await questions.elementHandle(),
      ),
    ).toBe(true);
    expect((await box(course)).top).toBeLessThan((await box(questions)).top);
  });

// A phone's course page shows the course alone, as R1's layout does: the conversation is in the page, not shown.
test('on a phone the course is shown alone, in the first screen', async ({
  page,
}, { project }) => {
  test.skip(project.name !== 'phone', 'the phone’s width');
  const { course } = await opened(page);
  const conversation = page.locator('section[aria-label="课程问答"]');
  await expect(conversation).toBeAttached();
  await expect(conversation).toBeHidden();
  expect((await box(course)).top).toBeLessThan(
    await page.evaluate(() => innerHeight),
  );
});

test('1440 wide: the conversation on the left, the course on its right', async ({
  page,
}, { project }) => {
  test.skip(project.name !== 'desktop', 'the desktop’s width');
  const { course, questions } = await opened(page);
  const left = await box(questions);
  const right = await box(course);
  expect(left.right).toBeLessThanOrEqual(right.left + 1);
  expect(Math.abs(left.top - right.top)).toBeLessThan(40);
});
