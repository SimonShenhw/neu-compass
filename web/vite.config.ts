import react from '@vitejs/plugin-react';
import { loadEnv } from 'vite';
import { defineConfig } from 'vitest/config';
import {
  PREVIEW_PORT,
  chooseApiBase,
  choosePublicBase,
  devPort,
} from './src/api/apiBase.ts';

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
  return {
    plugins: [react()],
    define: {
      __API_BASE_URL__: JSON.stringify(apiBase),
      __PUBLIC_BASE_URL__: JSON.stringify(publicBase),
    },
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
