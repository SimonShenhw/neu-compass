import { createHash } from 'node:crypto';
import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, it } from 'vitest';
const expected = {
  'course-404.json':
    'fdb9a0c698edcbbba0eee65b67b7e1a222d26f4d53a7dd56837220ec8d94ca4e',
  'course-cs-5100.json':
    'c8b5cf245eb6186642128536c2edda6cfe0e536f39e1a38bf44f0e2f06027e99',
  'course-cs-5800-requisites-unavailable.json':
    '97e0a5e9df9c83e58f4f37f19769c9e2e8acbd45562914822694cfb2fa5104f7',
  'course-cs-5800.json':
    'f47777b9bd82f4db46d2b3621f12abc91fbfcc1502cd7bf197ba5e404802f0ba',
  'course-cs-6140.json':
    'a05c730f7a3535be5809979f4242ecb978e51fd4f14a7ddafe9bcbe76a2f0bd3',
  'course-cs-7800.json':
    'fd3025988f7fdb23e6e0fd3b380aad7469395ec7b00739d5c819f85da00472eb',
  'course-ds-5220.json':
    '4e2c618875219086d11cf835a23c006b9f1e191be1c482825d27850e40f752bd',
  'expected/course-cs-5100.json':
    '03802a25ef084b4be7698bc78f835973f59c511676abac99d1bc468cd3ace097',
  'expected/course-cs-5800-requisites-unavailable.json':
    '09d4c45123aa5274e8aaacf84ce1a8a0d66321dd8731b42f3fb98311503b7f0c',
  'expected/course-cs-5800.json':
    '7be85e6742fb988a4fc01653c7a99cbf24199190f862029cf1e38c89e2722027',
  'expected/course-cs-6140.json':
    '66e7b28c14f33a84b2c54a54735e6fe975db5b63d63ae52add8bb726c2d0e68d',
  'expected/course-cs-7800.json':
    '1fa877b5794cec54de5e04de7b7fbe209e0e31192a56aa363e2ac731f62f56bb',
  'expected/course-ds-5220.json':
    'fb78270ea1af8ce0e546d372b18c5285e914a5f0dacbeed0fafff01296045a52',
};
it('all 13 comparison API exports and golden files preserve source bytes', () => {
  const root = resolve(process.cwd(), 'src/fixtures/compare');
  const actual = readdirSync(root, { recursive: true, withFileTypes: true })
    .filter((entry) => entry.isFile())
    .map((entry) => resolve(entry.parentPath, entry.name));
  expect(actual.sort()).toEqual(
    Object.keys(expected)
      .map((name) => resolve(root, name))
      .sort(),
  );
  for (const [name, hash] of Object.entries(expected))
    expect(
      createHash('sha256')
        .update(readFileSync(resolve(root, name)))
        .digest('hex'),
      name,
    ).toBe(hash);
});
