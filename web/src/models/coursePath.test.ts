import { expect, it } from 'vitest';
import {
  PUBLIC_BASE_URL,
  codeFromPath,
  coursePath,
  courseShareUrl,
  refLabel,
} from './coursePath';

it('a course page’s address is its code with hyphens, percent-encoded, and reads back for display', () => {
  expect(coursePath('CS 6140')).toBe('/course/CS-6140');
  expect(coursePath('c-cs-6140')).toBe('/course/c-cs-6140');
  expect(coursePath('CS 6140/../x?y#z')).toBe(
    '/course/CS-6140%2F..%2Fx%3Fy%23z',
  );
  expect(codeFromPath('CS-6140')).toBe('CS 6140');
});

it('a shared link names the site fixed at build time, the tests’ dev server here', () => {
  expect(PUBLIC_BASE_URL).toBe('http://127.0.0.1:5173');
  expect(courseShareUrl('CS 6140')).toBe(
    'http://127.0.0.1:5173/course/CS-6140',
  );
});

it('what an address names is said back on one line, without backticks, cut to 64 characters', () => {
  expect(refLabel('  CS\n\t5800 ')).toBe('CS 5800');
  expect(refLabel('`CS` 5800')).toBe('CS 5800');
  expect(refLabel('x　y z')).toBe('x y z');
  // Characters, not UTF-16 units: one outside the BMP counts once.
  expect(refLabel('𝟙'.repeat(70))).toBe('𝟙'.repeat(64));
  expect(refLabel('a'.repeat(64) + 'b')).toBe('a'.repeat(64));
});
