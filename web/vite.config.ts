import react from '@vitejs/plugin-react';
import { loadEnv } from 'vite';
import { defineConfig } from 'vitest/config';
import { chooseApiBase } from './src/api/apiBase.ts';

export default defineConfig(({ command, mode }) => {
  // R2b: the API address is fixed here, at build time (src/api/apiBase.ts says which one for which build).
  const { VITE_API_BASE_URL } = loadEnv(mode, process.cwd(), 'VITE_');
  const apiBase = chooseApiBase(command, mode, VITE_API_BASE_URL);
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
