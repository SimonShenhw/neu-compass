import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import type { ConfigEnv, Plugin, UserConfig } from 'vite';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { LOCAL_API, PRODUCTION_API } from '../src/api/apiBase.ts';
import config, {
  SECURITY_HEADERS_FILE,
  securityHeadersFile,
} from '../vite.config.ts';
import { securityHeaders } from './securityHeaders.ts';

afterEach(() => vi.unstubAllEnvs());

describe('the security headers of every response (R7)', () => {
  it('a policy that allows the site and its API only, the referrer policy, and nosniff', () => {
    expect(securityHeaders('https://api.neu-compass.me')).toEqual({
      'Content-Security-Policy':
        "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self'; " +
        "font-src 'self'; connect-src 'self' https://api.neu-compass.me; base-uri 'none'; " +
        "form-action 'none'; frame-ancestors 'none'",
      'Referrer-Policy': 'strict-origin-when-cross-origin',
      'X-Content-Type-Options': 'nosniff',
    });
    expect(
      securityHeaders('http://127.0.0.1:8000')['Content-Security-Policy'],
    ).toContain("connect-src 'self' http://127.0.0.1:8000;");
  });

  it('takes an origin and nothing else', () => {
    for (const value of [
      'https://api.neu-compass.me/',
      'https://api.neu-compass.me/v1',
      'https://api.neu-compass.me?x=1',
      "https://api.neu-compass.me; script-src 'unsafe-inline'",
    ])
      expect(() => securityHeaders(value), value).toThrow();
  });
});

describe('the build writes them, and the preview sends them (vite.config.ts)', () => {
  const configure = config as (env: ConfigEnv) => UserConfig;
  type Emitted = { type: string; fileName: string; source: string };
  // What the plugin of this configuration emits when it builds.
  function emitted(settings: UserConfig) {
    const plugin = (settings.plugins ?? [])
      .flat()
      .find(
        (entry) => (entry as Plugin).name === 'neu-compass:security-headers',
      ) as Plugin;
    const files: Emitted[] = [];
    (
      plugin.generateBundle as (this: { emitFile(file: Emitted): void }) => void
    ).call({ emitFile: (file) => files.push(file) });
    return files;
  }

  it('each build writes the headers for the API its bundle calls', () => {
    vi.stubEnv('VITE_API_BASE_URL', '');
    vi.stubEnv('VITE_PUBLIC_BASE_URL', '');
    vi.stubEnv('VITE_DEV_PORT', '');
    for (const [mode, api] of [
      ['production', PRODUCTION_API],
      ['dev-api', LOCAL_API],
    ] as const)
      expect(
        emitted(
          configure({
            command: 'build',
            mode,
            isSsrBuild: false,
            isPreview: false,
          }),
        ),
        mode,
      ).toEqual([
        {
          type: 'asset',
          fileName: '.vite/security-headers.json',
          source: `${JSON.stringify(securityHeaders(api), null, 2)}\n`,
        },
      ]);
    // A build for an API that VITE_API_BASE_URL names, as the image's is: that API's policy, not a default's (B36).
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.beta.example.test');
    expect(
      emitted(
        configure({
          command: 'build',
          mode: 'production',
          isSsrBuild: false,
          isPreview: false,
        }),
      ),
    ).toEqual([
      {
        type: 'asset',
        fileName: '.vite/security-headers.json',
        source: `${JSON.stringify(securityHeaders('https://api.beta.example.test'), null, 2)}\n`,
      },
    ]);
    expect(SECURITY_HEADERS_FILE).toBe('.vite/security-headers.json');
  });

  // A preview of the build in outDir, through the plugin's hook, and the headers it gives one response.
  function preview(outDir: string) {
    const middlewares: ((
      request: unknown,
      response: { setHeader(name: string, value: string): void },
      next: () => void,
    ) => void)[] = [];
    (
      securityHeadersFile('https://unused.example.test')
        .configurePreviewServer as (server: unknown) => void
    )({
      config: { root: outDir, build: { outDir: 'build' } },
      middlewares: {
        use: (handler: (typeof middlewares)[number]) =>
          middlewares.push(handler),
      },
    });
    const sent: Record<string, string> = {};
    let passedOn = false;
    for (const handler of middlewares)
      handler(
        {},
        { setHeader: (name, value) => (sent[name] = value) },
        () => (passedOn = true),
      );
    return { sent, passedOn };
  }

  it('a preview sends with every response the headers its build wrote', () => {
    const root = mkdtempSync(join(tmpdir(), 'nc-headers-'));
    try {
      const headers = securityHeaders('http://127.0.0.1:8000');
      mkdirSync(join(root, 'build', '.vite'), { recursive: true });
      writeFileSync(
        join(root, 'build', SECURITY_HEADERS_FILE),
        JSON.stringify(headers),
      );
      expect(preview(root)).toEqual({ sent: headers, passedOn: true });
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it('a preview of a build that wrote no headers does not start', () => {
    const root = mkdtempSync(join(tmpdir(), 'nc-headers-'));
    try {
      expect(() => preview(root)).toThrow(/is missing: .* so build first/);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it('every build and every preview has the plugin', () => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.beta.example.test');
    const names = (env: Omit<ConfigEnv, 'isSsrBuild'>) =>
      (configure({ ...env, isSsrBuild: false }).plugins ?? [])
        .flat()
        .map((plugin) => (plugin as Plugin).name);
    for (const env of [
      { command: 'build', mode: 'production', isPreview: false },
      { command: 'build', mode: 'dev-api', isPreview: false },
      { command: 'serve', mode: 'production', isPreview: true },
    ] as const)
      expect(names(env), JSON.stringify(env)).toContain(
        'neu-compass:security-headers',
      );
  });
});
