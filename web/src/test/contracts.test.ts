import { readFileSync, readdirSync } from 'node:fs';
import { resolve, relative } from 'node:path';
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

it('all direct dependencies are exact, stable pins and no HTTP or e2e library is installed', () => {
  const pkg = JSON.parse(
    readFileSync(resolve(root, 'package.json'), 'utf8'),
  ) as {
    dependencies: Record<string, string>;
    devDependencies: Record<string, string>;
  };
  for (const [name, version] of Object.entries({
    ...pkg.dependencies,
    ...pkg.devDependencies,
  })) {
    expect(version, name).toMatch(/^\d+\.\d+\.\d+$/);
    expect(name).not.toMatch(/tanstack|playwright|axios|ky$|superagent|got$/);
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

it('first-party TypeScript has no any types and production code does not create HTTP clients', () => {
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
      expect(node.kind, relative(root, path)).not.toBe(
        ts.SyntaxKind.AnyKeyword,
      );
      if (
        !path.includes('.test.') &&
        !path.includes(
          `${process.platform === 'win32' ? '\\' : '/'}test${process.platform === 'win32' ? '\\' : '/'}`,
        )
      ) {
        if (ts.isCallExpression(node) || ts.isNewExpression(node))
          expect(node.expression.getText(source), path).not.toMatch(
            /^(?:fetch|XMLHttpRequest|WebSocket|EventSource|navigator\.sendBeacon)$/,
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
