import { readFileSync, readdirSync } from 'node:fs';
import { resolve, relative, sep } from 'node:path';
import ts from 'typescript';
import { expect, it } from 'vitest';
import { courses } from '../fixtures/courses';

const root = process.cwd();
function files(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    if (
      ['node_modules', 'dist', 'coverage', '.vite', 'artifacts'].includes(
        entry.name,
      )
    )
      return [];
    const path = resolve(directory, entry.name);
    return entry.isDirectory() ? files(path) : [path];
  });
}

it('direct dependencies are exact, stable pins; TanStack Query is the only data library and no e2e library is installed', () => {
  for (const file of ['package.json', 'tools/openapi-types/package.json']) {
    const pkg = JSON.parse(readFileSync(resolve(root, file), 'utf8')) as {
      dependencies?: Record<string, string>;
      devDependencies?: Record<string, string>;
    };
    for (const [name, version] of Object.entries({
      ...pkg.dependencies,
      ...pkg.devDependencies,
    })) {
      expect(version, `${file}: ${name}`).toMatch(/^\d+\.\d+\.\d+$/);
      expect(name).not.toMatch(
        /playwright|puppeteer|axios|ky$|superagent|got$|devtools/,
      );
      if (name.includes('tanstack')) expect(name).toBe('@tanstack/react-query');
    }
  }
});

it('fixtures contain only the five approved course codes', () => {
  expect(courses.map((course) => course.code).sort()).toEqual([
    'CS 5100',
    'CS 5800',
    'CS 6140',
    'CS 7800',
    'DS 5220',
  ]);
});

// R2b: the API layer is the one place that talks to the network: the client, and the /chat stream next to it.
const NETWORK_CALL =
  /^(?:(?:window|globalThis|self)\.)?(?:fetch|XMLHttpRequest|WebSocket|EventSource)$|^navigator\.sendBeacon$/;
const ALLOWED_NETWORK_CALLS = new Set([
  'src/api/client.ts fetch',
  'src/api/chatStream.ts fetch',
]);

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
        if (ts.isCallExpression(node) || ts.isNewExpression(node)) {
          const callee = `${name} ${node.expression.getText(source)}`;
          if (NETWORK_CALL.test(node.expression.getText(source)))
            expect(ALLOWED_NETWORK_CALLS, callee).toContain(callee);
        }
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
