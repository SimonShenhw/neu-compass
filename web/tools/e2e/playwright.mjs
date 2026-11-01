// Playwright's command line, with its browser kept next to this file in .browsers (ignored by git) unless
// PLAYWRIGHT_BROWSERS_PATH names another place: the browser `npm run browser` installs is the one every run here finds,
// whichever terminal it starts from, instead of one in a per-user cache that another shell may not see (R6).
import { fileURLToPath } from 'node:url';

process.env.PLAYWRIGHT_BROWSERS_PATH ??= fileURLToPath(
  new URL('./.browsers', import.meta.url),
);
await import('@playwright/test/cli');
