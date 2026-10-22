import { createHash } from 'node:crypto';
import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, it } from 'vitest';

// SHA-256 of the 18 reviewer-provided API exports, captured before copying.
const expected = {
  'list-empty.json':
    '83cb2fd6ee6d0b9b4b3f39e9f84a0a70824e2573718dbea147c40df90c53fe33',
  'list-guest-without-moderation.json':
    '91c743c52ee68419050a3ca76420c04ad4bd7fd58275c48370e8f5c0d814a103',
  'list-guest.json':
    'c5f0ecc911a190fa9e33ff12ea468879c10fede944e2373cc775fb1c9c5dbea0',
  'list-member-0.json':
    '92027e027d66ec144feab73047efc50b85dacea2bed65ac2b2e34b332ab7b8a4',
  'list-member-1-after-publication.json':
    '9e7cb8d4539f2ef8393363fa7ec222ae9ccdb0c00d3eab139d771f6da12fa412',
  'list-member-1.json':
    '0c11c80dbe706b131a3eeb0487a11b520a35db6a62f51e97ba79bae65c5f864e',
  'list-member-2.json':
    '0debada115e639238a92c41305ca5e80474315c84ef64ffdca484f94d6ca9620',
  'upload-401-guest.json':
    '3eeafe6078d17d79761fa53dc87c5ddc5abc1d4d7e035cf54aabe181bf0dd600',
  'upload-401-unknown-user.json':
    '1c396a1fcdc9af0d02128c8f4eeba9f14645a2c98193db3a490419263d66fded',
  'upload-422-blank-company.json':
    '9dd8f5300a5f09cc28f9f16dcf0dfef817460bdbb4a86fd6778aa26865f9637f',
  'upload-422-duration.json':
    '5837440eee91032285b6b8f6b303e1d75e724cdc6a1c3399e664da44eef182b8',
  'upload-422-extra-field.json':
    '5420b9f9f24272ae81a6c8666384f55e8ef50aa744dc492ac1abca7020ad8676',
  'upload-503-no-moderation.json':
    '35971685f36794217c0f6c481e70414348a158794436762e953f050965dbc523',
  'upload-duplicate-approved.json':
    'b5e33b1aac505b0e7a808a4f2546339c45ad6a22fe9940e7b5e98b5cb3cba253',
  'upload-duplicate-pending.json':
    '6a33674bc4de5d2681277081e26524cf23f4613ef474a93c8363d4c6bbc0c4f5',
  'upload-duplicate-published.json':
    'd70fcff0df717a81f79f15fadcfdf82ee9107c48a84cb6efac9c80774a983e9b',
  'upload-duplicate-rejected.json':
    '37bdb8fc2e83b48b09aa62414abe10c998406d0a9c67c9a3655765c523260312',
  'upload-pending.json':
    '74ae04442da2ed9bb72d1aa61ff2c9cfd17b316ce848851e60ee1157c028581d',
};
it('all 18 API-export fixtures remain byte-for-byte unchanged', () => {
  const directory = resolve(process.cwd(), 'src/fixtures/coop');
  expect(readdirSync(directory).sort()).toEqual(Object.keys(expected).sort());
  for (const [name, hash] of Object.entries(expected))
    expect(
      createHash('sha256')
        .update(readFileSync(resolve(directory, name)))
        .digest('hex'),
      name,
    ).toBe(hash);
});
it('Co-op production modules do not persist drafts, log them or interpret HTML/Markdown', () => {
  for (const file of [
    'components/CoopCard.tsx',
    'components/CoopForm.tsx',
    'pages/CoopPage.tsx',
    'pages/CoopDemoPage.tsx',
    'models/coop.ts',
    'fixtures/coopDemo.ts',
  ]) {
    const source = readFileSync(resolve(process.cwd(), 'src', file), 'utf8');
    expect(source, file).not.toMatch(
      /localStorage|sessionStorage|console\.|dangerouslySetInnerHTML|react-markdown/,
    );
  }
});
