import { spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { renderHeaders } from './render-headers.ts';
import { securityHeaders } from './securityHeaders.ts';

describe('the headers as nginx add_header lines (R7)', () => {
  it('one line each, sent with every status', () => {
    expect(
      renderHeaders({
        'Referrer-Policy': 'strict-origin-when-cross-origin',
        'Content-Security-Policy': "default-src 'none'; img-src 'self'",
      }),
    ).toBe(
      'add_header Referrer-Policy "strict-origin-when-cross-origin" always;\n' +
        "add_header Content-Security-Policy \"default-src 'none'; img-src 'self'\" always;\n",
    );
  });

  it('refuses what nginx would read otherwise, and anything but headers', () => {
    for (const value of [
      'a $variable',
      'a "quote"',
      'a back\\slash',
      'two\nlines',
      'non-ASCII ’',
      '',
    ])
      expect(() => renderHeaders({ 'X-Test': value }), value).toThrow(
        'cannot be written for nginx',
      );
    for (const name of ['X Test', 'X-Test;', '1X', ''])
      expect(() => renderHeaders({ [name]: 'value' }), name).toThrow(
        'Not a header name',
      );
    expect(() => renderHeaders({ 'X-Test': 1 })).toThrow(
      'cannot be written for nginx',
    );
    for (const headers of [{}, [], null, 'X-Test: value'])
      expect(() => renderHeaders(headers), JSON.stringify(headers)).toThrow();
  });

  it('node runs it on a build’s file, as the image’s build stage does', () => {
    const directory = mkdtempSync(join(tmpdir(), 'nc-render-'));
    try {
      const headers = securityHeaders('https://api.neu-compass.me');
      const file = join(directory, 'security-headers.json');
      writeFileSync(file, JSON.stringify(headers));
      const run = spawnSync(
        process.execPath,
        [resolve('deploy/render-headers.ts'), file],
        { encoding: 'utf8' },
      );
      expect(run.status, run.stderr).toBe(0);
      expect(run.stdout).toBe(renderHeaders(headers));
      const without = spawnSync(
        process.execPath,
        [resolve('deploy/render-headers.ts')],
        { encoding: 'utf8' },
      );
      expect(without.status).not.toBe(0);
      expect(without.stderr).toContain('Usage: node deploy/render-headers.ts');
    } finally {
      rmSync(directory, { recursive: true, force: true });
    }
  });
});
