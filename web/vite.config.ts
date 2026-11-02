import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import react from '@vitejs/plugin-react';
import { loadEnv } from 'vite';
import type { Plugin } from 'vite';
import { defineConfig } from 'vitest/config';
import { securityHeaders } from './deploy/securityHeaders.ts';
import {
  PREVIEW_PORT,
  chooseApiBase,
  choosePublicBase,
  devPort,
} from './src/api/apiBase.ts';

// R6: the demo pages are on the dev server and in the tests, and in no build. A build gets demoRoutes.none.tsx where
// App imports demoRoutes (a path from the project root, which Vite resolves there), and stops if a demo page, its
// data or a test helper reaches it by any other import.
export const NO_DEMO_ROUTES = '/src/demoRoutes.none.tsx';
// Under the project's src/: the demo pages, shell and hooks, and the data behind them, by a name with Demo in it or in
// features/demo/; the tests' helpers; every fixture. With / for separators, as module IDs come on Windows, and the
// project root compared without case (Windows gives the drive either way). The rest keeps its case, or
// demoRoutes.none.tsx would read as a demo; a path written in another case resolves only on Windows, not in CI or
// the image's build (reviews A34, B34).
const DEMO_OR_TEST =
  /^(?:fixtures\/|test\/|features\/demo\/|demoRoutes\.tsx$|(?:[^/]*\/)*[^/]*(?:Demo|TestUtils)[^/]*$)/;
export function demoOrTestModule(id: string, root: string) {
  const source = `${root.replaceAll('\\', '/').replace(/\/+$/, '')}/src/`;
  const path = id.replaceAll('\\', '/');
  return (
    path.toLowerCase().startsWith(source.toLowerCase()) &&
    DEMO_OR_TEST.test(path.slice(source.length))
  );
}
export function noDemoModules(): Plugin {
  let root = '';
  return {
    name: 'neu-compass:no-demo-modules',
    configResolved(resolved) {
      root = resolved.root;
    },
    generateBundle(_options, bundle) {
      if (!root)
        this.error('The project root is not known, so nothing was checked.');
      for (const output of Object.values(bundle)) {
        if (output.type !== 'chunk') continue;
        const found = output.moduleIds.filter((id) =>
          demoOrTestModule(id, root),
        );
        if (found.length)
          this.error(
            `A build carries demo or test modules: ${found.join(', ')}`,
          );
      }
    },
  };
}

// R7: a build writes the headers nginx sends with every response (deploy/securityHeaders.ts) for the API its bundle
// calls. The web image renders them for nginx from this file (web/Dockerfile), and vite preview sends them from it, so
// the end-to-end tests run under the policy of the build they test.
export const SECURITY_HEADERS_FILE = '.vite/security-headers.json';
export function securityHeadersFile(apiBase: string): Plugin {
  return {
    name: 'neu-compass:security-headers',
    generateBundle() {
      this.emitFile({
        type: 'asset',
        fileName: SECURITY_HEADERS_FILE,
        source: `${JSON.stringify(securityHeaders(apiBase), null, 2)}\n`,
      });
    },
    configurePreviewServer(server) {
      const file = resolve(
        server.config.root,
        server.config.build.outDir,
        SECURITY_HEADERS_FILE,
      );
      if (!existsSync(file))
        throw new Error(
          `${file} is missing: a preview sends the headers its build wrote, so build first.`,
        );
      const headers = JSON.parse(readFileSync(file, 'utf8')) as Record<
        string,
        string
      >;
      server.middlewares.use((_request, response, next) => {
        for (const [name, value] of Object.entries(headers))
          response.setHeader(name, value);
        next();
      });
    },
  };
}

export default defineConfig(({ command, mode }) => {
  // R2b: the API address is fixed here, at build time (src/api/apiBase.ts says which one for which build); R3e: so is
  // the site a shared link names, and the dev server's port.
  const { VITE_API_BASE_URL, VITE_PUBLIC_BASE_URL, VITE_DEV_PORT } = loadEnv(
    mode,
    process.cwd(),
    'VITE_',
  );
  const apiBase = chooseApiBase(command, mode, VITE_API_BASE_URL);
  const port = devPort(VITE_DEV_PORT);
  const publicBase = choosePublicBase(
    command,
    mode,
    VITE_PUBLIC_BASE_URL,
    port,
  );
  const demos = command === 'serve';
  return {
    plugins: [
      react(),
      ...(demos ? [] : [noDemoModules()]),
      securityHeadersFile(apiBase),
    ],
    define: {
      __API_BASE_URL__: JSON.stringify(apiBase),
      __PUBLIC_BASE_URL__: JSON.stringify(publicBase),
      __DEMO_ROUTES__: JSON.stringify(demos),
    },
    resolve: demos
      ? {}
      : { alias: [{ find: /^\.\/demoRoutes$/, replacement: NO_DEMO_ROUTES }] },
    server: { host: '127.0.0.1', port, strictPort: true },
    preview: { host: '127.0.0.1', port: PREVIEW_PORT, strictPort: true },
    build: { manifest: true },
    test: {
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
      restoreMocks: true,
      clearMocks: true,
      maxWorkers: 4,
      css: { modules: { classNameStrategy: 'non-scoped' } },
    },
  };
});
