import { readFileSync, readdirSync } from 'node:fs';
import { resolve, relative, sep } from 'node:path';
import ts from 'typescript';
import { expect, it } from 'vitest';

const root = process.cwd();
function files(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    if (
      [
        'node_modules',
        'dist',
        'dist-dev-api',
        'coverage',
        '.vite',
        'artifacts',
        // What tools/e2e installs and what a run of it leaves (.gitignore).
        '.browsers',
        'test-results',
        'playwright-report',
      ].includes(entry.name)
    )
      return [];
    const path = resolve(directory, entry.name);
    return entry.isDirectory() ? files(path) : [path];
  });
}

type Package = {
  engines?: Record<string, string>;
  scripts?: Record<string, string>;
  dependencies?: Record<string, string>;
  devDependencies?: Record<string, string>;
};
const readPackage = (file: string) =>
  JSON.parse(readFileSync(resolve(root, file), 'utf8')) as Package;

it('direct dependencies are exact, stable pins; TanStack Query is the only data library and the site installs no e2e library', () => {
  for (const file of ['package.json', 'tools/openapi-types/package.json']) {
    const pkg = readPackage(file);
    for (const [name, version] of Object.entries({
      ...pkg.dependencies,
      ...pkg.devDependencies,
    })) {
      expect(version, `${file}: ${name}`).toMatch(/^\d+\.\d+\.\d+$/);
      expect(name).not.toMatch(
        /playwright|puppeteer|axios|ky$|superagent|got$|devtools|ofetch|wretch|node-fetch|cross-fetch|isomorphic-fetch|undici|socket\.io/,
      );
      if (name.includes('tanstack')) expect(name).toBe('@tanstack/react-query');
    }
  }
});

// R6's end-to-end tests are a package of their own: Playwright and axe's runner for it are in none of the site's
// dependencies, and nothing of the site imports them. The browser is Chromium's headless shell only, the download
// agreed for R6, into tools/e2e/.browsers (playwright.mjs).
it('Playwright is in tools/e2e only, exactly pinned, with the TypeScript and Node of the site, and src never imports it', () => {
  const site = readPackage('package.json');
  const e2e = readPackage('tools/e2e/package.json');
  expect(e2e.dependencies).toBeUndefined();
  expect(Object.keys(e2e.devDependencies ?? {}).sort()).toEqual([
    '@axe-core/playwright',
    '@playwright/test',
    '@types/node',
    'typescript',
  ]);
  for (const [name, version] of Object.entries(e2e.devDependencies ?? {}))
    expect(version, `tools/e2e: ${name}`).toMatch(/^\d+\.\d+\.\d+$/);
  for (const name of ['typescript', '@types/node'])
    expect(e2e.devDependencies?.[name], name).toBe(
      site.devDependencies?.[name],
    );
  expect(e2e.engines).toEqual(site.engines);
  expect(e2e.scripts?.browser).toBe(
    'node playwright.mjs install --only-shell chromium',
  );
  // Its tests are *.e2e.ts: a *.test.* or *.spec.* file would be Vitest's.
  expect(
    files(resolve(root, 'tools/e2e'))
      .map((path) => relative(root, path).split(sep).join('/'))
      .filter((name) => /\.(test|spec)\./.test(name)),
  ).toEqual([]);
  for (const path of files(resolve(root, 'src')).filter((path) =>
    /\.tsx?$/.test(path),
  )) {
    const source = ts.createSourceFile(
      path,
      readFileSync(path, 'utf8'),
      ts.ScriptTarget.Latest,
      true,
    );
    function visit(node: ts.Node) {
      const specifier =
        (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) &&
        node.moduleSpecifier &&
        ts.isStringLiteralLike(node.moduleSpecifier)
          ? node.moduleSpecifier.text
          : ts.isCallExpression(node) &&
              node.expression.kind === ts.SyntaxKind.ImportKeyword &&
              node.arguments[0] &&
              ts.isStringLiteralLike(node.arguments[0])
            ? node.arguments[0].text
            : null;
      if (specifier !== null)
        expect(specifier, relative(root, path)).not.toMatch(
          /tools\/e2e|playwright/,
        );
      ts.forEachChild(node, visit);
    }
    visit(source);
  }
});

it('the build for the API on this machine never lands where the production build does', () => {
  // dist/ only ever holds a build for the real API, so a dist/ handed to a deployment cannot point at a laptop (A26).
  const { scripts } = JSON.parse(
    readFileSync(resolve(root, 'package.json'), 'utf8'),
  ) as { scripts: Record<string, string> };
  expect(scripts.build).not.toContain('--outDir');
  expect(scripts['build:dev-api']).toContain(
    'vite build --mode dev-api --outDir dist-dev-api ',
  );
  expect(scripts['build:dev-api']).toMatch(
    / node scripts\/check-bundle\.mjs dist-dev-api$/,
  );
  expect(scripts['preview:dev-api']).toMatch(/ --outDir dist-dev-api$/);
});

// R2b: the API layer is the one place that talks to the network: the client, and the /chat stream next to it. Any
// mention of these names counts, not only a call: `const send = globalThis.fetch; send()` is a request too.
const NETWORK_NAMES = new Set([
  'fetch',
  'XMLHttpRequest',
  'WebSocket',
  'EventSource',
  'sendBeacon',
]);
const ALLOWED_NETWORK_USES = new Set([
  'src/api/client.ts fetch',
  'src/api/chatStream.ts fetch',
]);

it('the page sends other sites its origin only, wherever it is served from (R0 14.15)', () => {
  expect(readFileSync(resolve(root, 'index.html'), 'utf8')).toContain(
    '<meta name="referrer" content="strict-origin-when-cross-origin" />',
  );
});

it('the page describes itself to students, not as a prototype, and has an icon (R6)', () => {
  const html = readFileSync(resolve(root, 'index.html'), 'utf8');
  expect(html).toMatch(
    /<meta\s+name="description"\s+content="NEU-Compass 选课助手：/,
  );
  expect(html).not.toMatch(/原型|prototype|本地设计/i);
  expect(html).toContain(
    '<link rel="icon" href="/favicon.svg" type="image/svg+xml" />',
  );
  expect(readFileSync(resolve(root, 'public/favicon.svg'), 'utf8')).toMatch(
    /^<svg xmlns="http:\/\/www\.w3\.org\/2000\/svg" viewBox="0 0 32 32">/,
  );
});

it('first-party TypeScript has no any types and only the API client makes requests', () => {
  for (const path of files(resolve(root, 'src')).filter((path) =>
    /\.tsx?$/.test(path),
  )) {
    const name = relative(root, path).split(sep).join('/');
    const source = ts.createSourceFile(
      path,
      readFileSync(path, 'utf8'),
      ts.ScriptTarget.Latest,
      true,
    );
    function visit(node: ts.Node) {
      expect(node.kind, name).not.toBe(ts.SyntaxKind.AnyKeyword);
      if (!name.includes('.test.') && !name.startsWith('src/test/')) {
        // A name, a property (window.navigator.sendBeacon) or a string key (globalThis['fetch']).
        const used = ts.isIdentifier(node)
          ? node.text
          : ts.isElementAccessExpression(node) &&
              ts.isStringLiteralLike(node.argumentExpression)
            ? node.argumentExpression.text
            : null;
        if (used !== null && NETWORK_NAMES.has(used))
          expect(ALLOWED_NETWORK_USES, `${name} ${used}`).toContain(
            `${name} ${used}`,
          );
      }
      ts.forEachChild(node, visit);
    }
    visit(source);
  }
});

it('all authored files use LF and CSS colors and font sizes come from tokens', () => {
  for (const path of files(root)) {
    const content = readFileSync(path, 'utf8');
    expect(content.includes('\r'), relative(root, path)).toBe(false);
    if (path.endsWith('.css') && !path.endsWith('tokens.css')) {
      const withoutComments = content.replace(/\/\*[\s\S]*?\*\//g, '');
      expect(withoutComments, path).not.toMatch(
        /#[\da-f]{3,8}\b|rgba?\(|hsla?\(/i,
      );
      for (const match of withoutComments.matchAll(/font-size\s*:\s*([^;]+)/g))
        expect(match[1], path).toMatch(/^var\(--/);
      expect(withoutComments).not.toMatch(/https?:/);
    }
  }
});

it('normal text token pairs meet a 4.5:1 contrast threshold', () => {
  const source = readFileSync(resolve(root, 'src/styles/tokens.css'), 'utf8');
  function token(name: string) {
    const value = source.match(
      new RegExp(`--${name}:\\s*(#[0-9a-f]{6});`, 'i'),
    )?.[1];
    if (!value) throw new Error(`Missing ${name}`);
    return value;
  }
  function luminance(hex: string) {
    function channel(offset: number) {
      const value = Number.parseInt(hex.slice(offset, offset + 2), 16) / 255;
      return value <= 0.04045
        ? value / 12.92
        : ((value + 0.055) / 1.055) ** 2.4;
    }
    return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5);
  }
  for (const [foreground, background] of [
    ['ink', 'surface'],
    ['ink2', 'surface'],
    ['ink3', 'canvas'],
    ['ink3', 'surface'],
    ['accent', 'accent-soft'],
    ['accent-ink', 'accent'],
    ['ok', 'canvas'],
  ] as const) {
    const a = luminance(token(foreground));
    const b = luminance(token(background));
    expect(
      (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05),
      `${foreground}/${background}`,
    ).toBeGreaterThanOrEqual(4.5);
  }
});
