import { createHash } from 'node:crypto';
import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, it } from 'vitest';
const frozen = {
  'expected/cs-5008-one-year-repeated-leaf.json':
    '95608b143637cf1b9b112137021d3ac0b6a8215a29f8ca1199306761574584cc',
  'expected/cs-5800-nothing-listed.json':
    '85743d6c161f719de9737f930e039fcbd75aabaf3072f6d3d9f53cd9c62c0cc6',
  'expected/cs-6140-program-table-broken.json':
    '01b6f5e2915d9963b53342705dca90888519b05e1173498699fc74a84b24f059',
  'expected/cs-6140-program-table-missing.json':
    '6ecae6beb7ec03c726ce563ba8fe0935e364aa4a396b63ae87f534bdceca84d4',
  'expected/cs-6140-requisites-table-broken.json':
    '0b3314c010bca582c514c48e3b46e865265e32b516c265fe93de301856134f51',
  'expected/cs-6140-requisites-table-missing.json':
    'e8dda7246adf9ce7e6af376a7d7dd903b366fc69369761322fd75e69d25cc61a',
  'expected/cs-6140-two-years.json':
    '3ae0a3ecac37e2798d383e19c45e08bd9db5817771a4e96fc75d698bc7cdc99d',
  'expected/cs-6220-one-unusable-row.json':
    '6e72cc8a42631f47f2bd4e69dbc45c3052c31d8349e138415393ce4a74d46561',
  'expected/cs-7800-legacy-edges-only.json':
    'b214f9b515e2a69cb46ae918ff540ef164e14993a7b525855be7ecd7a4db40bf',
  'expected/derived-foreign-plan-link.json':
    '2eaa3cf5c3b2cbbaae274b2b1cbdfb07ae9013d78e4d8afff07027a63bbd3139',
  'expected/derived-foreign-source-link.json':
    '7c5d5af6241a16c437302f7f22daf11d59d8f81c77d6e003750bf3ddfee58a63',
  'expected/derived-identity-mismatch.json':
    'ab17e73215b0c897b968bfb5e5aff470022f581020d599c66bdab6328a8f778a',
  'expected/derived-invalid-tree.json':
    '0d20af682600bc74a32e555150bd7f037e8cddd347caa7033e46c7f2e6194c3e',
  'expected/derived-older-api-no-requisites.json':
    '862d632affeae3c1beff08a51278a29107c05dc851f0f1fddeaa0320f77f99af',
  'expected/derived-two-documents-one-year.json':
    'ddd2f77eb6526d6965f4ad482377dbe0a9a4b29f320c81524d0fc61a76dde55e',
  'expected/ds-5220-unparsed-old-record.json':
    'a5c16e95625bd0506d3a7ed359041337a020650eb96f7fa9455c556cf93167f1',
  'cs-5008-one-year-repeated-leaf.json':
    '2afe0aa50156a378aaed233accafac357339cc50b803bba20b294e7dae306688',
  'cs-5800-nothing-listed.json':
    'ef05648d1c378ef681bac165a3e903c4b1d259d0731d96ef7030584b2fff256e',
  'cs-6140-program-table-broken.json':
    'dec3fdc59ffd911a2836665d3f50ca7206c219a0a1b611e23fce8665d7aaa174',
  'cs-6140-program-table-missing.json':
    'fac7819b152c983ed6ffb2c60dfff6e667fe8bfefc21d2230409b0cc041e3980',
  'cs-6140-requisites-table-broken.json':
    '20314dbe78292e22f0cd8bdea5abb5d0615aa961ec6fb07ae15cd425d54b7bf6',
  'cs-6140-requisites-table-missing.json':
    '7b1f908d680a9da8481116332c4b83fe2a1798ea25a2cfe8e3cf107a9269de93',
  'cs-6140-two-years.json':
    '9e8dd8e785a5c48b3b9dae0d88a519cd00f60cd1cdf63084b63af1aecc9b542b',
  'cs-6220-one-unusable-row.json':
    '3e70061f94dbe99cf91a459359c06702e75326bb44f677010154908ceb792a35',
  'cs-7800-legacy-edges-only.json':
    'd260fdcaeffba1e070a5b2eab16a1978e7ac8da3c53afe77ba83a17ea7b81eb5',
  'derived-foreign-plan-link.json':
    'e68166c3aeaf850be0aa9c687fbc55b63512cf698eb42f45e7cae412c3f59de8',
  'derived-foreign-source-link.json':
    '960364b8de134fafa33fbb414097d9bd9126223d8f197bbd8b5eedc3f4b4c574',
  'derived-identity-mismatch.json':
    '8248f1c10640214e55e48d4affd64e914716531f66d6eec6b9099233ea05929d',
  'derived-invalid-tree.json':
    'bfc2d0c5859de08e05b56272da77c8bb56b51ec75b0792bd07d70209bbca2ac8',
  'derived-older-api-no-requisites.json':
    'a12f6e88681da661344b43fdff1e791d230d8661d6db29cc8fd89db3b3bd8122',
  'derived-two-documents-one-year.json':
    '6d818ed8bcfac19aecafe3bd2b7ad788986f1dac544aa106a650914d88b1d2ff',
  'ds-5220-unparsed-old-record.json':
    '0d5ca988a2950d7c2ef43f51b383ea0be4e61f227644e4e4b957bb3e498a69a4',
} as const;
it('all 32 reviewer fixtures and Python goldens preserve original bytes and filenames', () => {
  const root = resolve('src/fixtures/requisites');
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
  for (const [path, hash] of Object.entries(frozen)) {
    const bytes = readFileSync(resolve(root, path));
    expect(createHash('sha256').update(bytes).digest('hex'), path).toBe(hash);
  }
});
