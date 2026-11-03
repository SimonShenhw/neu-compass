import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { QUERY_LOG_FALLBACK } from '../layout/AskBar';

// The words the web copies from the API's Python (R3e), checked against it, so a change on either side shows here
// (review B32). Until R8 this also checked nine sentences copied from the Streamlit page; R8 deleted the page, so they
// are the web's own words now. The Python is there only in a whole checkout: the mutation scripts' snapshots copy web/
// alone, and skip these. Vitest runs in web/, as every test here that reads a file expects (contracts.test.ts); run
// from anywhere else, these fail instead of skipping (recheck 1).
const web = process.cwd();
const inWeb = existsSync(resolve(web, 'vite.config.ts'));
const repo = resolve(web, '..');
const checkout = existsSync(resolve(repo, 'pyproject.toml'));
const whole = existsSync(resolve(repo, 'api', 'privacy_text.py'));

it('runs in web/, so the checkout around it can be found', () => {
  expect(inWeb).toBe(true);
});

// In a whole checkout the Python must be found: a file that moved or went fails here, where it would only skip the
// comparisons below (R8 deleted app/, which this checked for, and they were skipped until this test).
it.skipIf(!checkout)('finds the Python in a whole checkout', () => {
  expect(whole).toBe(true);
});

describe.skipIf(inWeb && !whole)('words copied from the Python side', () => {
  it.each([['api/privacy_text.py', QUERY_LOG_FALLBACK]])(
    '%s says %s',
    (file, words) => {
      expect(readFileSync(resolve(repo, file), 'utf8')).toContain(words);
    },
  );
});
