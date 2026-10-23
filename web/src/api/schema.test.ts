import { spawnSync } from 'node:child_process';
import {
  existsSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const web = process.cwd();
const generator = resolve(web, 'tools/openapi-types/generate.mjs');
// CI installs the generator before these run; a local checkout without it skips them, visibly.
const installed = existsSync(
  resolve(web, 'tools/openapi-types/node_modules/openapi-typescript'),
);
const run = (...args: string[]) =>
  spawnSync(process.execPath, [generator, ...args], {
    cwd: web,
    encoding: 'utf8',
    timeout: 60_000,
  });

describe.skipIf(!installed)(
  'the generated API types (needs npm ci --prefix tools/openapi-types)',
  () => {
    it('src/api/schema.ts is what openapi.json generates', () => {
      const result = run('--check');
      expect(result.status, result.stderr).toBe(0);
    });

    it(
      '--check fails on a stale file and writes nothing; a plain run writes it',
      {
        timeout: 60_000,
      },
      () => {
        const directory = mkdtempSync(join(tmpdir(), 'nc-schema-'));
        try {
          const target = join(directory, 'schema.ts');
          writeFileSync(target, 'stale\n');
          const stale = run('--check', '--target', target);
          expect(stale.status).toBe(1);
          expect(stale.stderr).toContain('out of date');
          expect(readFileSync(target, 'utf8')).toBe('stale\n');
          expect(run('--target', target).status).toBe(0);
          expect(readFileSync(target, 'utf8')).toBe(
            readFileSync(resolve(web, 'src/api/schema.ts'), 'utf8'),
          );
          expect(run('--check', '--target', target).status).toBe(0);
          const source = join(directory, 'openapi.json');
          const document = JSON.parse(
            readFileSync(resolve(web, 'openapi.json'), 'utf8'),
          );
          document.components.schemas.PublicConfigResponse.properties.extra_flag =
            { type: 'boolean', title: 'Extra Flag' };
          writeFileSync(source, JSON.stringify(document));
          expect(
            run('--check', '--source', source, '--target', target).status,
          ).toBe(1);
        } finally {
          rmSync(directory, { recursive: true, force: true });
        }
      },
    );
  },
);
