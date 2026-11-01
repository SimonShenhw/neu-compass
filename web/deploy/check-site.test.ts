import { describe, expect, it, vi } from 'vitest';
import { checkSite } from './check-site.ts';
import { securityHeaders } from './securityHeaders.ts';

const SITE = 'http://site.test';
const API = 'https://api.neu-compass.me';
const SCRIPT = '/assets/index-Abc123.js';
const INDEX = `<!doctype html><html><head><script type="module" crossorigin src="${SCRIPT}"></script></head><body><div id="root"></div></body></html>`;
const MISSING = '/assets/no-such-chunk-0000.js';

// A stand-in for the web image as deploy/nginx.conf has it serve the build, with one thing wrong at a time: the
// checker must pass the first and fail every other. Behind a stubbed fetch, as every test here keeps off the network.
const FAULTS = {
  'no CSP on a 404': `${MISSING}: Content-Security-Policy is null`,
  'no security headers on a 304':
    '/ with If-None-Match: X-Content-Type-Options is null',
  'a policy for another API': '/healthz: Content-Security-Policy is',
  'a deep link is a 404': "/course/CS-6140: 404, not the app's index.html",
  'the build’s .vite/ is served':
    "/.vite/manifest.json: 200, not the app's index.html",
  'assets are not cached': `${SCRIPT}: Cache-Control is "no-cache"`,
  'a JavaScript file as text': `${SCRIPT}: Content-Type is "text/plain"`,
  'a missing chunk is index.html': `${MISSING}: 200, not a plain 404`,
  'a missing chunk is an empty 200': `${MISSING}: 200, not a plain 404`,
  'index.html as text': '/: Content-Type is "text/plain"',
  'a missing chunk is cached for a year': `${MISSING}: Cache-Control is "public, max-age=31536000, immutable", not null`,
  'index.html is cached': '/: Cache-Control is "max-age=3600"',
  'the health check is cached': '/healthz: Cache-Control is "max-age=60"',
  'no ETag': '/: no ETag',
  'the server names its version': '/: Server is "nginx/1.30.6"',
} as const;
type Fault = keyof typeof FAULTS | 'none';

function standIn(fault: Fault) {
  const policy = securityHeaders(
    fault === 'a policy for another API' ? 'https://api.example.test' : API,
  );
  return (path: string, request: Headers): Response => {
    function send(
      status: number,
      body: string | null,
      extra: Record<string, string>,
    ) {
      const headers = new Headers(extra);
      headers.set(
        'Server',
        fault === 'the server names its version' ? 'nginx/1.30.6' : 'nginx',
      );
      for (const [name, value] of Object.entries(policy)) {
        if (fault === 'no security headers on a 304' && status === 304)
          continue;
        if (
          fault === 'no CSP on a 404' &&
          status === 404 &&
          name === 'Content-Security-Policy'
        )
          continue;
        headers.set(name, value);
      }
      return new Response(body, { status, headers });
    }
    const index = () =>
      request.get('If-None-Match') === '"v1"'
        ? send(304, null, { 'Cache-Control': 'no-cache', ETag: '"v1"' })
        : send(200, INDEX, {
            'Content-Type':
              fault === 'index.html as text'
                ? 'text/plain'
                : 'text/html; charset=utf-8',
            'Cache-Control':
              fault === 'index.html is cached' ? 'max-age=3600' : 'no-cache',
            ...(fault === 'no ETag' ? {} : { ETag: '"v1"' }),
          });
    if (path === '/healthz')
      return send(200, 'ok\n', {
        'Content-Type': 'text/plain; charset=utf-8',
        'Cache-Control':
          fault === 'the health check is cached' ? 'max-age=60' : 'no-store',
      });
    if (path === '/favicon.svg')
      return send(200, '<svg xmlns="http://www.w3.org/2000/svg"></svg>', {
        'Content-Type': 'image/svg+xml',
        'Cache-Control': 'no-cache',
      });
    if (path === SCRIPT)
      return send(200, 'export {};', {
        'Content-Type':
          fault === 'a JavaScript file as text'
            ? 'text/plain'
            : 'application/javascript; charset=utf-8',
        'Cache-Control':
          fault === 'assets are not cached'
            ? 'no-cache'
            : 'public, max-age=31536000, immutable',
      });
    if (path.startsWith('/assets/')) {
      if (fault === 'a missing chunk is index.html') return index();
      if (fault === 'a missing chunk is an empty 200') return send(200, '', {});
      return send(
        404,
        '<html><body>404 Not Found</body></html>',
        fault === 'a missing chunk is cached for a year'
          ? { 'Cache-Control': 'public, max-age=31536000, immutable' }
          : {},
      );
    }
    if (
      path === '/.vite/manifest.json' &&
      fault === 'the build’s .vite/ is served'
    )
      return send(200, '{}', { 'Content-Type': 'application/json' });
    if (path === '/course/CS-6140' && fault === 'a deep link is a 404')
      return send(404, 'not here', {});
    return index();
  };
}

async function check(fault: Fault) {
  const site = standIn(fault);
  const requested: string[] = [];
  vi.stubGlobal('fetch', async (url: URL | string, init?: RequestInit) => {
    const target = new URL(String(url));
    expect(target.origin, 'only the site is asked').toBe(SITE);
    expect(init?.redirect, 'redirects are seen, not followed').toBe('manual');
    requested.push(target.pathname);
    return site(target.pathname, new Headers(init?.headers));
  });
  const failures = await checkSite(SITE, API);
  return { failures, requested };
}

describe('deploy/check-site.ts, the check of what the web image serves (R7)', () => {
  it('passes a site served as nginx.conf has it, asking for each kind of response', async () => {
    const { failures, requested } = await check('none');
    expect(failures).toEqual([]);
    expect(requested).toEqual([
      '/healthz',
      '/',
      '/index.html',
      '/course/CS-6140',
      '/programs/cs-ms',
      '/assets',
      '/.vite/manifest.json',
      '/.vite/security-headers.json',
      '/favicon.svg',
      SCRIPT,
      MISSING,
      '/',
    ]);
  });

  for (const [fault, failure] of Object.entries(FAULTS))
    it(`fails one where ${fault}`, async () => {
      const { failures } = await check(fault as Fault);
      expect(
        failures.some((line) => line.startsWith(failure)),
        failures.join('\n'),
      ).toBe(true);
    });
});
