import { expect } from '@playwright/test';
import type { Page } from '@playwright/test';
import {
  answer,
  answered,
  ask,
  askBox,
  box,
  conversation,
  field,
  landed,
  optIn,
  test,
} from './support';

// R6: the ask box held at the bottom of the window (AskBar.module.css, styles/base.css), which jsdom cannot lay out.
// With answer feedback on, as production has it: held with the box, the opt-in and its notice took about half a
// phone's window and all of a zoomed one (review A34). What is held now is the query log's sentence and the field.

// The share of the window the held part may take.
const HELD = { desktop: 0.15, phone: 0.3, zoomed: 0.3 };

async function held(page: Page) {
  return askBox(page).evaluate((form: HTMLElement) => ({
    position: getComputedStyle(form).position,
    bottom: getComputedStyle(form).bottom,
    height: form.offsetHeight,
    measured: getComputedStyle(document.documentElement).getPropertyValue(
      '--ask-bar-height',
    ),
    window: innerHeight,
  }));
}

test('held at the bottom: the query log sentence and the field, its height on html; the opt-in under it, in the page', async ({
  page,
}, { project }) => {
  await page.goto('/');
  await landed(page);
  const form = await held(page);
  expect(form.position).toBe('sticky');
  expect(form.bottom).toBe('0px');
  expect(form.height / form.window).toBeLessThanOrEqual(
    HELD[project.name as 'desktop' | 'phone'],
  );
  expect(form.measured).toBe(`${form.height}px`);
  // The opt-in, its notice: a landmark of their own after the form, scrolling with the page (recheck 1 of round 34).
  await expect(askBox(page).getByRole('checkbox')).toHaveCount(0);
  await expect(optIn(page)).toBeAttached();
  const capture = page.getByRole('region', { name: '保存回答' });
  expect(
    await capture.evaluate((section) => getComputedStyle(section).position),
  ).toBe('static');
  expect((await box(capture)).top).toBeGreaterThanOrEqual(
    (await box(askBox(page))).bottom - 1,
  );
});

// Zoomed: 1093×614 is a 1366×768 viewport at 125 %, 960×540 a 1920×1080 one at 200 % (a 1080 p screen in full
// screen); both are still held.
for (const [width, height] of [
  [1093, 614],
  [960, 540],
] as const)
  test(`held in a zoomed ${width}×${height} window, and no taller than a third of it`, async ({
    page,
  }, { project }) => {
    test.skip(project.name !== 'desktop', 'one run of each size');
    await page.setViewportSize({ width, height });
    await page.goto('/');
    await landed(page);
    const form = await held(page);
    expect(form.position).toBe('sticky');
    expect(form.height / form.window).toBeLessThanOrEqual(HELD.zoomed);
  });

// Lower than 500 px (a phone held sideways, a laptop zoomed further) nothing is held: the box is at the page's end.
for (const [width, height] of [
  [844, 390],
  [640, 360],
  [320, 256],
] as const)
  test(`not held in a ${width}×${height} window, and nothing scrolls sideways or keeps room for it`, async ({
    page,
  }, { project }) => {
    test.skip(project.name !== 'desktop', 'one run of each size');
    await page.setViewportSize({ width, height });
    await page.goto('/');
    await landed(page);
    expect((await held(page)).position).toBe('static');
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(width);
    const margins = await page
      .locator('#main-content *')
      .evaluateAll((elements) => [
        ...new Set(elements.map((e) => getComputedStyle(e).scrollMarginBottom)),
      ]);
    expect(margins).toEqual(['0px']);
  });

test('with no ask box on the page, nothing in main keeps room for one', async ({
  page,
}) => {
  await page.goto('/programs');
  await expect(
    page.getByRole('region', { name: '培养方案列表' }),
  ).toBeVisible();
  await expect(askBox(page)).toHaveCount(0);
  const margins = await page
    .locator('#main-content *')
    .evaluateAll((elements) => [
      ...new Set(elements.map((e) => getComputedStyle(e).scrollMarginBottom)),
    ]);
  expect(margins).toEqual(['0px']);
});

// html's scroll-padding-bottom, the first way, moved the page down whenever one of the box's own controls took focus
// (review A34). A long page, scrolled a little.
test('clicking into the question field moves the page nowhere', async ({
  page,
}) => {
  await page.goto('/course/CS-6140');
  await expect(page.getByRole('region', { name: '课程详情' })).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 120));
  const before = await page.evaluate(() => scrollY);
  expect(before).toBeGreaterThan(0);
  await field(page).click();
  await expect(field(page)).toBeFocused();
  expect(await page.evaluate(() => scrollY)).toBe(before);
});

// Tab through an answer with its votes: what takes focus in main is clear of the box, its focus ring too (WCAG
// 2.4.11; the margin counts the ring since recheck 1 of round 34). In a window the answer does not fit above the box,
// so that Tab scrolls the page: on the desktop the 1080 p screen at 200 % above, as 1440×900 holds all of the answer
// (review B35) and 1093×614 scrolls for one control only (recheck 1 of round 35).
test('Tab through an answer: every control in the conversation, focus ring and all, stays above the box', async ({
  page,
}, { project }) => {
  if (project.name === 'desktop')
    await page.setViewportSize({ width: 960, height: 540 });
  await page.goto('/');
  await landed(page);
  await optIn(page).check();
  await ask(page, 'CS 5800 讲什么？');
  await answered(page, 1);
  await expect(
    answer(page, 1).getByRole('group', { name: '回答反馈' }),
  ).toBeVisible();
  await conversation(page).focus();
  const seen: string[] = [];
  const scrolledTo: string[] = [];
  let y = await page.evaluate(() => scrollY);
  for (let step = 0; step < 40; step += 1) {
    await page.keyboard.press('Tab');
    const where = await page.evaluate(() => {
      const element = document.activeElement as HTMLElement | null;
      const form = document.querySelector('form[aria-label="提问"]');
      if (!element || !form) return null;
      if (form.contains(element) || !element.closest('#main-content'))
        return { done: true as const };
      const style = getComputedStyle(element);
      return {
        done: false as const,
        name:
          element.getAttribute('aria-label') ??
          element.textContent?.trim().slice(0, 30) ??
          element.tagName,
        bottom:
          element.getBoundingClientRect().bottom +
          parseFloat(style.outlineOffset) +
          parseFloat(style.outlineWidth),
        boxTop: form.getBoundingClientRect().top,
        y: scrollY,
      };
    });
    if (!where || where.done) break;
    seen.push(where.name);
    if (where.y !== y) scrolledTo.push(where.name);
    y = where.y;
    expect(where.bottom, where.name).toBeLessThanOrEqual(where.boxTop + 0.5);
  }
  // It went through the conversation's controls, the votes among them, before reaching the box, and the page
  // scrolled to show some of them.
  expect(seen.length).toBeGreaterThan(3);
  expect(seen.join(' / ')).toMatch(/有帮助|没帮助/);
  expect(scrolledTo).not.toEqual([]);
});
