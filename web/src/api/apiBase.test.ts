import type { ConfigEnv, Plugin, UserConfig } from 'vite';
import { afterEach, describe, expect, it, vi } from 'vitest';
import config, {
  NO_DEMO_ROUTES,
  demoOrTestModule,
  noDemoModules,
} from '../../vite.config';
import {
  DEV_API_MODE,
  LOCAL_API,
  PRODUCTION_API,
  PRODUCTION_SITE,
  apiBaseUrl,
  chooseApiBase,
  choosePublicBase,
  devPort,
} from './apiBase';

afterEach(() => vi.unstubAllEnvs());

describe('the API address, fixed at build time', () => {
  it('falls back when the variable is missing or blank', () => {
    expect(apiBaseUrl(undefined, PRODUCTION_API)).toBe(
      'https://api.neu-compass.me',
    );
    expect(apiBaseUrl('  ', LOCAL_API)).toBe('http://127.0.0.1:8000');
  });

  it('takes an https origin, or plain http on this machine', () => {
    for (const [value, origin] of [
      ['https://api.neu-compass.me/', 'https://api.neu-compass.me'],
      ['https://API.example.test:8443', 'https://api.example.test:8443'],
      [' http://localhost:8000 ', 'http://localhost:8000'],
      ['http://127.0.0.1:8000/', 'http://127.0.0.1:8000'],
      ['http://[::1]:8000', 'http://[::1]:8000'],
    ] as const)
      expect(apiBaseUrl(value, PRODUCTION_API), value).toBe(origin);
  });

  it('refuses anything a request path could not be appended to safely', () => {
    for (const value of [
      'api.neu-compass.me',
      'http://api.neu-compass.me',
      'http://localhost.example.com:8000',
      'ftp://localhost',
      'https://api.neu-compass.me/v1',
      'https://api.neu-compass.me/?x=1',
      'https://api.neu-compass.me/#top',
      'https://user:pass@api.neu-compass.me',
      'https://user@api.neu-compass.me',
      'https://:pass@api.neu-compass.me',
      'javascript:alert(1)',
    ])
      expect(() => apiBaseUrl(value, LOCAL_API), value).toThrow(
        /VITE_API_BASE_URL/,
      );
  });
});

describe('which API a bundle talks to', () => {
  const other = 'https://api.example.test';

  it('a production build: the production API or another https one, never plain http', () => {
    expect(chooseApiBase('build', 'production', undefined)).toBe(
      PRODUCTION_API,
    );
    expect(chooseApiBase('build', 'production', other)).toBe(other);
    for (const value of [LOCAL_API, 'http://localhost:8000'])
      expect(() => chooseApiBase('build', 'production', value), value).toThrow(
        'A production build needs an https API',
      );
  });

  it('a build for the dev API, and the dev server: this machine’s, unless the variable names another', () => {
    for (const [command, mode] of [
      ['build', DEV_API_MODE],
      ['serve', 'development'],
    ] as const) {
      expect(chooseApiBase(command, mode, undefined)).toBe(LOCAL_API);
      expect(chooseApiBase(command, mode, other)).toBe(other);
    }
    expect(DEV_API_MODE).toBe('dev-api');
  });

  it('any other build must name its API', () => {
    for (const value of [undefined, '', ' '])
      expect(() => chooseApiBase('build', 'staging', value)).toThrow(
        'A build in mode "staging" needs VITE_API_BASE_URL.',
      );
    expect(chooseApiBase('build', 'staging', other)).toBe(other);
    expect(chooseApiBase('build', 'staging', LOCAL_API)).toBe(LOCAL_API);
  });

  it('the tests use this machine’s API, whatever the environment says', () => {
    expect(chooseApiBase('serve', 'test', other)).toBe(LOCAL_API);
  });

  it('vite.config.ts builds the choice into the bundle', () => {
    vi.stubEnv('VITE_API_BASE_URL', '');
    vi.stubEnv('VITE_PUBLIC_BASE_URL', '');
    vi.stubEnv('VITE_DEV_PORT', '');
    const configure = config as (env: ConfigEnv) => UserConfig;
    const bundled = (command: ConfigEnv['command'], mode: string) =>
      configure({ command, mode, isSsrBuild: false, isPreview: false }).define;
    expect(bundled('build', 'production')).toEqual({
      __API_BASE_URL__: JSON.stringify(PRODUCTION_API),
      __PUBLIC_BASE_URL__: JSON.stringify(PRODUCTION_SITE),
      __DEMO_ROUTES__: 'false',
    });
    expect(bundled('build', DEV_API_MODE)).toEqual({
      __API_BASE_URL__: JSON.stringify(LOCAL_API),
      __PUBLIC_BASE_URL__: JSON.stringify('http://127.0.0.1:4173'),
      __DEMO_ROUTES__: 'false',
    });
    expect(() => bundled('build', 'staging')).toThrow(
      /needs VITE_API_BASE_URL/,
    );
    vi.stubEnv('VITE_API_BASE_URL', other);
    expect(bundled('serve', 'development')).toEqual({
      __API_BASE_URL__: JSON.stringify(other),
      __PUBLIC_BASE_URL__: JSON.stringify('http://127.0.0.1:5173'),
      __DEMO_ROUTES__: 'true',
    });
    expect(bundled('serve', 'test')).toEqual({
      __API_BASE_URL__: JSON.stringify(LOCAL_API),
      __PUBLIC_BASE_URL__: JSON.stringify('http://127.0.0.1:5173'),
      __DEMO_ROUTES__: 'true',
    });
  });

  it('the dev server takes another port when 5173 is taken, and its shared links follow', () => {
    vi.stubEnv('VITE_API_BASE_URL', '');
    vi.stubEnv('VITE_PUBLIC_BASE_URL', '');
    vi.stubEnv('VITE_DEV_PORT', '5300');
    const configure = config as (env: ConfigEnv) => UserConfig;
    const dev = configure({
      command: 'serve',
      mode: 'development',
      isSsrBuild: false,
      isPreview: false,
    });
    expect(dev.server).toMatchObject({ port: 5300, strictPort: true });
    expect(dev.define).toMatchObject({
      __PUBLIC_BASE_URL__: JSON.stringify('http://127.0.0.1:5300'),
    });
  });
});

describe('the site a shared link names (R3e)', () => {
  it('every build for students names the production site, a beta too, unless another https one is named', () => {
    for (const mode of ['production', 'beta'])
      expect(choosePublicBase('build', mode, undefined, 5173), mode).toBe(
        PRODUCTION_SITE,
      );
    expect(
      choosePublicBase('build', 'beta', 'https://beta.example.test/', 5173),
    ).toBe('https://beta.example.test');
    expect(() =>
      choosePublicBase('build', 'production', 'http://127.0.0.1:5173', 5173),
    ).toThrow('A shared link must name an https site');
    expect(() =>
      choosePublicBase('build', 'production', 'https://x.test/page', 5173),
    ).toThrow(/VITE_PUBLIC_BASE_URL must be an https origin/);
  });

  it('the dev server, a dev-api build and the tests name this machine', () => {
    expect(choosePublicBase('serve', 'development', undefined, 5300)).toBe(
      'http://127.0.0.1:5300',
    );
    expect(
      choosePublicBase('serve', 'development', 'http://localhost:5300/', 5300),
    ).toBe('http://localhost:5300');
    expect(choosePublicBase('build', DEV_API_MODE, undefined, 5300)).toBe(
      'http://127.0.0.1:4173',
    );
    expect(
      choosePublicBase('serve', 'test', 'https://x.example.test', 5300),
    ).toBe('http://127.0.0.1:5173');
  });

  it('the dev port: 5173 by default, otherwise a port from 1024 up', () => {
    expect(devPort(undefined)).toBe(5173);
    expect(devPort(' ')).toBe(5173);
    expect(devPort('5300')).toBe(5300);
    // Both ends of the range are ports (review B32).
    expect(devPort('1024')).toBe(1024);
    expect(devPort('65535')).toBe(65535);
    for (const value of ['80', '1023', '65536', '5300x', '-1', '5e3'])
      expect(() => devPort(value), value).toThrow('VITE_DEV_PORT');
  });
});

describe('the demo pages: on the dev server and in the tests, in no build (R6)', () => {
  const configure = config as (env: ConfigEnv) => UserConfig;
  const at = (command: ConfigEnv['command'], mode: string) =>
    configure({ command, mode, isSsrBuild: false, isPreview: false });
  const names = (settings: UserConfig) =>
    (settings.plugins ?? []).flat().map((plugin) => (plugin as Plugin).name);

  it('every build swaps App’s demo routes for none, and checks what it carries', () => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.beta.example.test');
    for (const mode of ['production', DEV_API_MODE, 'beta']) {
      const built = at('build', mode);
      expect(built.resolve, mode).toEqual({
        alias: [{ find: /^\.\/demoRoutes$/, replacement: NO_DEMO_ROUTES }],
      });
      expect(names(built), mode).toContain('neu-compass:no-demo-modules');
    }
    expect(NO_DEMO_ROUTES).toBe('/src/demoRoutes.none.tsx');
    for (const mode of ['development', 'test']) {
      const served = at('serve', mode);
      expect(served.resolve, mode).toEqual({});
      expect(names(served), mode).not.toContain('neu-compass:no-demo-modules');
    }
  });

  type Hook = (
    this: { error(message: string): never },
    ...args: unknown[]
  ) => void;
  const context = {
    error(message: string): never {
      throw new Error(message);
    },
  };
  // A build of the project at root whose chunks hold these modules, through the plugin's own hooks: the first its
  // entry, the others what it loads later.
  function chunks(root: string | null, ...modules: string[][]) {
    const plugin = noDemoModules();
    if (root !== null) (plugin.configResolved as Hook).call(context, { root });
    (plugin.generateBundle as Hook).call(
      context,
      {},
      Object.fromEntries([
        ...modules.map((moduleIds, index) => [
          index === 0 ? 'assets/index.js' : `assets/chunk-${index}.js`,
          { type: 'chunk', moduleIds },
        ]),
        ['assets/index.css', { type: 'asset' }],
      ]),
    );
  }
  // One chunk holding these modules.
  const build = (root: string | null, ...moduleIds: string[]) =>
    chunks(root, moduleIds);

  it('a build stops when a demo page or shell, a demo’s data, a fixture or a test helper reaches it by any import', () => {
    // As Vite gives them: the root with / and module IDs with /; and on Windows, IDs with \ and another drive case.
    const root = 'H:/neu-compass/web';
    const src = (path: string) => `${root}/src/${path}`;
    const windows = (path: string) =>
      `h:\\neu-compass\\web\\src\\${path.replaceAll('/', '\\')}`;
    const main = src('main.tsx');
    for (const found of [
      src('pages/CompareDemoPage.tsx'),
      windows('pages/SearchLandingDemoPage.tsx'),
      src('pages/CompareDemoPage.module.css?used'),
      src('features/demo/OfflineDemoShell.tsx'),
      // Whatever else the demo shell's folder holds, and the landing demo's conversation (reviews A34, B34).
      src('features/demo/sample.ts'),
      src('features/search-landing/LandingDemoConversation.tsx'),
      src('features/programs/useProgramDemoLoad.ts'),
      src('demoRoutes.tsx'),
      src('fixtures/compareDemo.ts'),
      windows('fixtures/programs/curriculum-cs-ms.json'),
      src('pages/searchRouteTestUtils.tsx'),
      src('test/withApi.tsx'),
    ])
      expect(() => build(root, main, found), found).toThrow(
        `A build carries demo or test modules: ${found}`,
      );
    // The same project's root, given with a trailing /.
    expect(() => build(`${root}/`, main, src('demoRoutes.tsx'))).toThrow(
      `A build carries demo or test modules: ${src('demoRoutes.tsx')}`,
    );
    expect(() =>
      build(
        `${root}/`,
        main,
        src('demoRoutes.none.tsx'),
        src('pages/CompareRoute.tsx'),
        windows('models/compareList.ts'),
        src('features/programs/ProgramCurriculum.tsx'),
        // Another package's own src/ is not this project's.
        `${root}/node_modules/some-lib/src/fixtures/data.js`,
        `${root}/node_modules/x/src/test/a.js`,
      ),
    ).not.toThrow();
    expect(demoOrTestModule('/work/web/src/test/a.ts', '/work/web')).toBe(true);
    expect(demoOrTestModule('/work/web/src/test/a.ts', '/work/other')).toBe(
      false,
    );
  });

  // A real build has more than one chunk; one that loads a demo page later (a lazy route) carries it in the second
  // (review B34).
  it('a demo page in any chunk stops the build, not only in the first', () => {
    const root = 'H:/neu-compass/web';
    const demo = `${root}/src/pages/CoopDemoPage.tsx`;
    expect(() =>
      chunks(
        root,
        [`${root}/src/main.tsx`],
        [`${root}/src/pages/CompareRoute.tsx`],
        [demo],
      ),
    ).toThrow(`A build carries demo or test modules: ${demo}`);
  });

  it('a build whose project root never came stops instead of checking nothing', () => {
    expect(() => build(null, '/work/web/src/main.tsx')).toThrow(
      'The project root is not known',
    );
  });
});
