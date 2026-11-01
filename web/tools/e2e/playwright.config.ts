import { defineConfig } from '@playwright/test';
import { API, WEB } from './tests/support';

// R6's end-to-end tests, in Chromium's headless shell: a build of web/ for the API on this machine (npm run
// build:dev-api, served by preview:dev-api) against the dev API (tests/support/dev_api.py), with answer feedback on and
// 90 days of query log, as production has them. Synthetic data and the fake Google only. In CI Playwright starts both;
// where they already run (on Windows the dev API runs in WSL) it uses them, and globalSetup checks they are the ones.
const ci = Boolean(process.env.CI);

export default defineConfig({
  testDir: './tests',
  // Not *.test.* or *.spec.*: Vitest, in web/, would take those for its own.
  testMatch: '**/*.e2e.ts',
  // One dev API for every test: an upload or a deleted account changes what the next test sees, so one at a time.
  workers: 1,
  fullyParallel: false,
  forbidOnly: ci,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: ci ? [['list'], ['html', { open: 'never' }]] : [['list']],
  globalSetup: './globalSetup.ts',
  use: {
    baseURL: WEB,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  // Each test in both window sizes, but for the flows and the build's own checks, once on the desktop, and the phone's
  // menu, on the phone.
  projects: [
    {
      name: 'desktop',
      testIgnore: ['**/menu.e2e.ts'],
      use: { browserName: 'chromium', viewport: { width: 1440, height: 900 } },
    },
    {
      name: 'phone',
      testIgnore: ['**/flows.e2e.ts', '**/build.e2e.ts'],
      use: { browserName: 'chromium', viewport: { width: 390, height: 844 } },
    },
  ],
  webServer: [
    {
      // After `uv sync --frozen --extra dev`, as CI's other job installs the API.
      command:
        'uv run --frozen --no-sync python -m tests.support.dev_api --answer-feedback --query-log-retention-days 90',
      cwd: '../../..',
      url: `${API}/ready`,
      reuseExistingServer: !ci,
      timeout: 180_000,
    },
    {
      command: 'npm run preview:dev-api',
      cwd: '../..',
      url: WEB,
      reuseExistingServer: !ci,
    },
  ],
});
