import { createHash } from 'node:crypto';
import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, it } from 'vitest';
const expected = {
  'delete-401-account-gone.json':
    '4d008915ee01a815ca6cd7019aafea9a339415a1286032fde62b48d12b77a4c3',
  'delete-401-cookie-not-valid.json':
    'd2db5bdb0180ba88bc3539208ac84f0f77591c2e4b00dbe2c9debf089d449da8',
  'delete-403-cross-site.json':
    '57051114484b4019fcf3c8b6fc6d02a597ffe797bdaab60740e504c231ec4b83',
  'delete-422-wrong-word.json':
    '992963952f1402e1a5a1af53d9410f2c574a031c893014a173f08f25cd00a709',
  'delete-ok-nothing-else.json':
    'e1c53deda5f0b3b8ba843b0c9e222ef71cf5a3b3fc4ab5368dca6397fb095d3a',
  'delete-ok.json':
    '19425182491dd7965714765786c92fac34754dfa920f9721ce596874a8d80044',
  'privacy-30-days-feedback-no-contact.json':
    'fc830691299ddb1cbc589f4c538e4b88e70da2ffbfc0aacfda6aad904ca374c5',
  'privacy-90-days-feedback-contact.json':
    'ea8d974c520a93c774cd804f15a2f5bf3d53e20fe17cac43f265bb2dc096ce20',
  'privacy-no-cleanup-feedback-contact.json':
    '538f4c390444f2ca6e21d7097d7bfe5b1c6e35519388ef1a95ac6c306e1ce49a',
  'privacy-no-cleanup-feedback-off.json':
    'b167083c58003957cba9e26bbd64c75681c490e7ffbcc4e2be5f59f1bf21c847',
};
it('all 10 privacy API exports preserve source bytes', () => {
  const root = resolve(process.cwd(), 'src/fixtures/privacy');
  expect(readdirSync(root).sort()).toEqual(Object.keys(expected).sort());
  for (const [name, hash] of Object.entries(expected))
    expect(
      createHash('sha256')
        .update(readFileSync(resolve(root, name)))
        .digest('hex'),
      name,
    ).toBe(hash);
});
