// Generate src/api/schema.ts from openapi.json (written by scripts/export_openapi.py) with openapi-typescript,
// formatted with the web package's own Prettier settings, so `format:check` and this script agree on every byte.
// `--check` writes nothing and exits 1 when the target differs; CI runs it. `--source` and `--target` change the two
// files (the tests use them); by default they are web/openapi.json and web/src/api/schema.ts.
//
// This is a package of its own because openapi-typescript 7 declares `typescript@^5` as a peer and the web package
// uses TypeScript 6; the generated file is plain TypeScript that both read. Prettier is resolved upwards from here,
// from web/node_modules, so run `npm ci` in web/ first, then `npm ci --prefix tools/openapi-types`.
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import openapiTS, { astToString } from 'openapi-typescript';
import * as prettier from 'prettier';

const web = resolve(import.meta.dirname, '../..');
const args = process.argv.slice(2);
const option = (name, fallback) => {
  const index = args.indexOf(name);
  return index >= 0 && args[index + 1] ? resolve(args[index + 1]) : fallback;
};
const source = option('--source', resolve(web, 'openapi.json'));
const target = option('--target', resolve(web, 'src/api/schema.ts'));
const header =
  '// Generated from openapi.json by `npm run gen:api` (openapi-typescript). Do not edit by hand:\n' +
  '// change the API, run `python scripts/export_openapi.py` from the repository root, then `npm run gen:api`.\n\n';

const ast = await openapiTS(JSON.parse(readFileSync(source, 'utf8')), {
  silent: true,
});
// The settings of the real file, wherever the target is, so a test's temporary target is formatted the same way.
const config = await prettier.resolveConfig(resolve(web, 'src/api/schema.ts'));
const text = await prettier.format(header + astToString(ast), {
  ...config,
  parser: 'typescript',
});

if (args.includes('--check')) {
  const current = existsSync(target) ? readFileSync(target, 'utf8') : null;
  if (current !== text) {
    console.error(
      `${target} is out of date: run \`npm run gen:api\` and commit it.`,
    );
    process.exit(1);
  }
  console.info(`${target} is up to date.`);
} else {
  writeFileSync(target, text);
  console.info(`Wrote ${target}.`);
}
