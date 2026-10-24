import { createHash } from 'node:crypto';
import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, it } from 'vitest';
const frozen = {
  'expected/cs-5800-identity-only.json':
    '9e931b0a906a9ca46a2311944a73b7332c405d12c5e7d097d267cd07571831d0',
  'expected/cs-6140-everything.json':
    '358c384dbaf2c010ad8412ae197e35498684bfb415e1d63f64fbc8c0fa1c8585',
  'expected/derived-empty-strings.json':
    'a92d0baceac9422ca46150662514f51bad1d92aa9c4fd7461439629cb62720b3',
  'expected/derived-foreign-catalog-link.json':
    '4e0ffad33a2889ab154b7f7e6b168b514cc20b7072408f9d6ddacad46a2109a2',
  'expected/derived-malformed-snapshot-id.json':
    '87a1efc4316bd95490bd48e2fd415a43d0b29f35aba175b90a1a76cb47c142ac',
  'expected/derived-older-api-no-evidence.json':
    '08877aa226142f908c9880b2d599e67dcb95c92d0a17607b5c1f732cc82c0e26',
  'expected/derived-unknown-codes.json':
    'f5d97d937991ba06fdf0427c8c43c32a47e5393b0a332b3a33960ae3d7d18ffb',
  'expected/ds-5220-conflicts.json':
    '647d5b64c19103e58b82faf452c341925b9ec6c43eec29e55c2dbcf81b2117b6',
  'expected/synth-cs-9999-test-record.json':
    'e1d8f261e952d0d073ea27042151a8ae901b0295eb03c16c80988434d442fe26',
  'cs-5800-identity-only.json':
    '533120116667105fa78c63781e4d39a684a8138afd909177c459ac63ccbe1b4f',
  'cs-6140-everything.json':
    'ad568bed379ff115f3744a580b85d4f786c348514476be8447d5d56a2d618a1f',
  'derived-empty-strings.json':
    '7c727a0c00f11ef4e8d8c917f914329041309209005bfae1aa76b9ad0651137e',
  'derived-foreign-catalog-link.json':
    'd582d5087ca78d1cf768cf58925a675a4b258621adcc092f66bf2147e836218d',
  'derived-malformed-snapshot-id.json':
    '89982248452658a8cd7222c7346e423a3c26c7a000d1b0b6718c12bebf42abee',
  'derived-older-api-no-evidence.json':
    '7889f1f722048cf88e55916808d4adcba37057a6e1e40bd5a7863a09b9c0aac1',
  'derived-unknown-codes.json':
    '0cbe0b8af8228eaec57a0afa78cdb4d93733b87308eccdd0a4605814a3d36720',
  'ds-5220-conflicts.json':
    '06b33b299c94c0be60f424ab1305f4e52d8dae3f5250b365227864fa9b635532',
  'synth-cs-9999-test-record.json':
    '4d7f9a2bea15d7c8d433971c68b139c1782616070c35351adb948c8e59c54619',
} as const;
it('all 18 reviewer detail fixtures and goldens preserve original bytes and filenames', () => {
  const root = resolve('src/fixtures/course-detail');
  expect(
    readdirSync(root)
      .filter((p) => p.endsWith('.json'))
      .sort(),
  ).toEqual(
    Object.keys(frozen)
      .filter((p) => !p.includes('/'))
      .sort(),
  );
  expect(readdirSync(resolve(root, 'expected')).sort()).toEqual(
    Object.keys(frozen)
      .filter((p) => p.includes('/'))
      .map((p) => p.slice(9))
      .sort(),
  );
  for (const [path, hash] of Object.entries(frozen))
    expect(
      createHash('sha256')
        .update(readFileSync(resolve(root, path)))
        .digest('hex'),
      path,
    ).toBe(hash);
});
