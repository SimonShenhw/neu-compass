import { API, WEB } from './tests/support';

// Before any test: the dev API answers as production is configured, and the preview serves a build that asks it. A dev
// API started without --answer-feedback would fail every ask-box test for the wrong reason, and quietly: with answer
// feedback off the box is only shorter (review A34 found the held box too tall with it on). A production build served
// on the preview's port would send every test's questions to the real API.
export default async function globalSetup() {
  const config = (await (await fetch(`${API}/config`)).json()) as {
    answer_feedback_enabled?: unknown;
  };
  const privacy = (await (await fetch(`${API}/privacy`)).json()) as {
    capture_notice?: unknown;
  };
  if (config.answer_feedback_enabled !== true || !privacy.capture_notice)
    throw new Error(
      'The dev API on 8000 has answer feedback off: start it with --answer-feedback --query-log-retention-days 90.',
    );
  const page = await (await fetch(WEB)).text();
  const entry = page.match(/<script type="module" crossorigin src="([^"]+)"/);
  const code =
    page.includes('<div id="root">') && entry
      ? await (await fetch(new URL(entry[1]!, WEB))).text()
      : '';
  // The API's address is fixed in the bundle when it is built (src/api/apiBase.ts).
  if (!code.includes(API) || code.includes('api.neu-compass.me'))
    throw new Error(
      `${WEB} does not serve a build for the dev API: npm run build:dev-api, then npm run preview:dev-api, in web/.`,
    );
}
