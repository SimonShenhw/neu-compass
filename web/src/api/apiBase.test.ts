import type { ConfigEnv, UserConfig } from 'vite';
import { afterEach, describe, expect, it, vi } from 'vitest';
import config from '../../vite.config';
import {
  DEV_API_MODE,
  LOCAL_API,
  PRODUCTION_API,
  apiBaseUrl,
  chooseApiBase,
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
    const configure = config as (env: ConfigEnv) => UserConfig;
    const bundled = (command: ConfigEnv['command'], mode: string) =>
      configure({ command, mode, isSsrBuild: false, isPreview: false }).define;
    expect(bundled('build', 'production')).toEqual({
      __API_BASE_URL__: JSON.stringify(PRODUCTION_API),
    });
    expect(bundled('build', DEV_API_MODE)).toEqual({
      __API_BASE_URL__: JSON.stringify(LOCAL_API),
    });
    expect(() => bundled('build', 'staging')).toThrow(
      /needs VITE_API_BASE_URL/,
    );
    vi.stubEnv('VITE_API_BASE_URL', other);
    expect(bundled('serve', 'development')).toEqual({
      __API_BASE_URL__: JSON.stringify(other),
    });
    expect(bundled('serve', 'test')).toEqual({
      __API_BASE_URL__: JSON.stringify(LOCAL_API),
    });
  });
});
