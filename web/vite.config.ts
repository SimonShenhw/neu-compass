import react from '@vitejs/plugin-react';
import { loadEnv } from 'vite';
import { defineConfig } from 'vitest/config';
import { LOCAL_API, PRODUCTION_API, apiBaseUrl } from './src/api/apiBase.ts';

export default defineConfig(({ command, mode }) => {
  // R2b: the API address is fixed here, at build time. A production build talks to the production API unless
  // VITE_API_BASE_URL says otherwise; the dev server, tests and other modes default to the API on this machine.
  const { VITE_API_BASE_URL } = loadEnv(mode, process.cwd(), 'VITE_');
  const apiBase = apiBaseUrl(
    VITE_API_BASE_URL,
    command === 'build' && mode === 'production' ? PRODUCTION_API : LOCAL_API,
  );
  return {
    plugins: [react()],
    define: { __API_BASE_URL__: JSON.stringify(apiBase) },
    server: { host: '127.0.0.1', port: 5173, strictPort: true },
    preview: { host: '127.0.0.1', port: 4173, strictPort: true },
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
