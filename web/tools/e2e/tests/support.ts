import { expect, test as base } from '@playwright/test';
import type { Locator, Page } from '@playwright/test';

// The preview of the build, and the dev API it was built for (src/api/apiBase.ts: PREVIEW_PORT and LOCAL_API).
export const WEB = 'http://127.0.0.1:4173';
export const API = 'http://127.0.0.1:8000';

// Every test: no page of its browser context asks anything of anyone but the site and its API (the fonts are bundled,
// the icons inline), in whatever state the test leaves it, a comparison table, a chosen plan, an account (review A35).
// And nothing it does, a dialog, a select, a stream, a sign-in, is refused by the CSP the preview sends: the build's own
// (deploy/securityHeaders.ts), the policy nginx sends in production (R7). The browser reports each refusal as a
// securitypolicyviolation event, in any document of any page of the context, a page the test opens later included
// (review A36). The reports are counted once every page has run one more frame after the test's last step; a refusal
// later than that goes unseen. A test that makes one on purpose takes cspViolations and empties it.
export const test = base.extend<{
  noThirdParty: void;
  cspViolations: string[];
}>({
  noThirdParty: [
    async ({ context }, use) => {
      const others = new Set<string>();
      context.on('request', (request) => {
        const { protocol, origin } = new URL(request.url());
        if (
          (protocol === 'http:' || protocol === 'https:') &&
          origin !== WEB &&
          origin !== API
        )
          others.add(origin);
      });
      await use();
      expect([...others], 'requests to other origins').toEqual([]);
    },
    { auto: true },
  ],
  cspViolations: [
    async ({ context }, use) => {
      const violations: string[] = [];
      await context.exposeBinding(
        'reportCspViolation',
        (_source, report: string) => {
          violations.push(report);
        },
      );
      await context.addInitScript(() => {
        // On the window, once. A page opened with window.open keeps the window of its first, blank document across
        // its first navigation, while that document and anything listening on it is replaced, and this script does
        // not run again (Chromium): the window's listener still hears the new document's refusals, which bubble up.
        const watched = window as unknown as {
          reportCspViolation(report: string): void;
          cspWatched?: true;
        };
        if (watched.cspWatched) return;
        watched.cspWatched = true;
        window.addEventListener('securitypolicyviolation', (event) => {
          const where = event.sourceFile
            ? ` at ${event.sourceFile}:${event.lineNumber}`
            : '';
          watched.reportCspViolation(
            `${event.effectiveDirective} refused ${event.blockedURI}${where}`,
          );
        });
      });
      await use(violations);
      // A report is an event queued after the refusal: let each page run once more before counting.
      for (const page of context.pages())
        await page
          .evaluate(
            () =>
              new Promise((resolve) =>
                requestAnimationFrame(() => setTimeout(resolve)),
              ),
          )
          .catch(() => undefined);
      expect(violations, 'CSP violations').toEqual([]);
    },
    { auto: true },
  ],
});

// The dev API's scripted answer ends so (tests/support/dev_api.py's ANSWER).
const ANSWER_END = '没有调用模型。）';

export const askBox = (page: Page) => page.getByRole('form', { name: '提问' });
export const field = (page: Page) =>
  page.getByRole('textbox', { name: '课程问题' });
export const sendButton = (page: Page) =>
  page.getByRole('button', { name: '发送问题' });
export const conversation = (page: Page) =>
  page.getByRole('group', { name: '对话' });
export const answer = (page: Page, turn: number) =>
  page.getByRole('article', { name: `第 ${turn} 轮回答` });
export const optIn = (page: Page) =>
  page
    .getByRole('region', { name: '保存回答' })
    .getByRole('checkbox', { name: /^允许保存/ });

export async function landed(page: Page) {
  await expect(
    page.getByRole('region', { name: '搜索落地内容' }),
  ).toBeVisible();
}

export async function ask(page: Page, question: string) {
  await field(page).fill(question);
  await field(page).press('Enter');
}

export async function answered(page: Page, turn: number) {
  await expect(answer(page, turn)).toContainText(ANSWER_END);
}

export type Box = { top: number; bottom: number; left: number; right: number };
export const box = (locator: Locator): Promise<Box> =>
  locator.evaluate((element) => {
    const { top, bottom, left, right } = element.getBoundingClientRect();
    return { top, bottom, left, right };
  });

// The newest question's top edge, where it was brought into view.
export const newestQuestionTop = (page: Page) =>
  page
    .locator('[data-kind="question"]')
    .last()
    .evaluate((element) => element.getBoundingClientRect().top);

export async function atTheTop(page: Page) {
  await expect
    .poll(async () => Math.abs(await newestQuestionTop(page)))
    .toBeLessThanOrEqual(1);
}

// Every call of scrollIntoView, by what it was called on, from the page's first script: what "scrolls nowhere" means.
export async function countScrolls(page: Page) {
  await page.addInitScript(() => {
    const calls: string[] = [];
    Object.assign(window, { scrollCalls: calls });
    const original = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = function (
      this: Element,
      ...options: Parameters<Element['scrollIntoView']>
    ) {
      calls.push(this.getAttribute('data-kind') ?? this.tagName);
      return original.apply(this, options);
    };
  });
}
export const scrolls = (page: Page) =>
  page.evaluate(
    () => (window as unknown as { scrollCalls: string[] }).scrollCalls,
  );

// The fake Google of the dev API: the sidebar's login, then the account's link on the sign-in page there.
export async function signIn(page: Page, account: string) {
  await page.getByRole('button', { name: '用 NEU 邮箱登录' }).click();
  await page.getByRole('link', { name: account, exact: true }).click();
  await expect(page.getByRole('button', { name: '退出登录' })).toBeVisible();
}
