import { describe, expect, it } from 'vitest';
import { LOCAL_API, PRODUCTION_API, apiBaseUrl } from './apiBase';

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
