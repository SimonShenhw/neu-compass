import { describe, expect, it, vi } from 'vitest';
import { checkSite } from './check-site.ts';
import { securityHeaders } from './securityHeaders.ts';

const SITE = 'http://site.test';
const API = 'https://api.neu-compass.me';
const SHARE = 'https://beta.neu-compass.me';
const SCRIPT = '/assets/index-Abc123.js';
const STYLESHEET = '/assets/index-Def456.css';
const MISSING = '/assets/no-such-chunk-0000.js';
const MALFORMED = '/course/%zz';
const ENTRY = `<script type="module" crossorigin src="${SCRIPT}"></script>`;
const STYLES = `<link rel="stylesheet" crossorigin href="${STYLESHEET}">`;
const page = (head: string) =>
  `<!doctype html><html><head>${head}</head><body><div id="root"></div></body></html>`;
const WELCOME =
  '<!DOCTYPE html><html><head><title>Welcome to nginx!</title></head><body><h1>Welcome to nginx!</h1></body></html>';
const IMMUTABLE = 'public, max-age=31536000, immutable';

// A stand-in for the web image as deploy/nginx.conf has it serve the build, with one thing wrong at a time: the
// checker must pass the first and fail every other, each on the line that names what is wrong, so that every check it
// makes has a fault of its own here (review B36). Behind a stubbed fetch, as every test here keeps off the network.
const FAULTS = {
  // The health check.
  'the health check says OK': '/healthz: 200 "OK"',
  'the health check as bytes':
    '/healthz: Content-Type is "application/octet-stream"',
  'the health check is cached': '/healthz: Cache-Control is "max-age=60"',
  'a policy for another API': '/healthz: Content-Security-Policy is',
  // index.html at /, and when revalidated.
  'index.html behind a redirect': '/: 301',
  'nginx’s welcome page everywhere': "/: not the app's index.html",
  'index.html as text': '/: Content-Type is "text/plain"',
  'index.html is cached': '/: Cache-Control is "max-age=3600"',
  'the server names its version': '/: Server is "nginx/1.30.6"',
  'the entry script retyped (Rocket Loader)':
    '/: no module script under /assets/',
  'index.html without its stylesheet': '/: no stylesheet under /assets/',
  'no ETag': '/: no ETag',
  'If-None-Match ignored': '/ with If-None-Match: 200, not 304',
  'no security headers on a 304':
    '/ with If-None-Match: X-Content-Type-Options is null',
  // The other paths that are index.html.
  'a deep link is a 404': "/course/CS-6140: 404, not the app's index.html",
  '/assets redirected to /assets/ (try_files $uri/)':
    "/assets: 301, not the app's index.html",
  'the build’s .vite/ is served':
    "/.vite/manifest.json: 200, not the app's index.html",
  'a page path cached an hour':
    '/programs/cs-ms: Cache-Control is "max-age=3600"',
  'a deep link without the security headers':
    '/course/CS-6140: Content-Security-Policy is null',
  // The icon.
  'the icon is index.html': '/favicon.svg: 200, not the icon',
  'the icon as text': '/favicon.svg: Content-Type is "text/plain"',
  'the icon cached for a year': `/favicon.svg: Cache-Control is "${IMMUTABLE}"`,
  'the icon without the security headers':
    '/favicon.svg: Content-Security-Policy is null',
  // The built files.
  'the entry script is a 404': `${SCRIPT}: 404`,
  'a JavaScript file as text': `${SCRIPT}: Content-Type is "text/plain"`,
  'assets are not cached': `${SCRIPT}: Cache-Control is "no-cache"`,
  'the entry script without the security headers': `${SCRIPT}: Content-Security-Policy is null`,
  'a stylesheet as text': `${STYLESHEET}: Content-Type is "text/plain"`,
  'a bundle built for another API': `${SCRIPT}: no ${API} in the bundle`,
  'a bundle whose links name compass': `${SCRIPT}: no ${SHARE} in the bundle`,
  // A chunk that is not there.
  'a missing chunk is index.html': `${MISSING}: 200, not a plain 404`,
  'a missing chunk is an empty 200': `${MISSING}: 200, not a plain 404`,
  'a missing chunk is a 404 with index.html (error_page)': `${MISSING}: 404, not a plain 404`,
  'a missing chunk is cached for a year': `${MISSING}: Cache-Control is "${IMMUTABLE}", not null`,
  'no CSP on a 404': `${MISSING}: Content-Security-Policy is null`,
  // Requests nothing here reads.
  'a large body is a 413':
    'POST /course/CS-6140 with 1100000 bytes: 413, not 405',
  'a 405 without the security headers':
    'POST /course/CS-6140: Content-Security-Policy is null',
  'a malformed request is the page': `${MALFORMED}: 200, not 400`,
  'no security headers on nginx’s own 400': `${MALFORMED}: Content-Security-Policy is null`,
} as const;
type Fault = keyof typeof FAULTS | 'none';

function standIn(fault: Fault) {
  const policy = securityHeaders(
    fault === 'a policy for another API' ? 'https://api.example.test' : API,
  );
  return (
    path: string,
    request: Headers,
    method: string,
    bodySize: number,
  ): Response => {
    // Which answers go out without the security headers, or without the CSP alone.
    const bare = (status: number) =>
      (fault === 'no security headers on a 304' && status === 304) ||
      (fault === 'no security headers on nginx’s own 400' && status === 400) ||
      (fault === 'a 405 without the security headers' && method === 'POST') ||
      (fault === 'a deep link without the security headers' &&
        method === 'GET' &&
        path === '/course/CS-6140') ||
      (fault === 'the icon without the security headers' &&
        path === '/favicon.svg') ||
      (fault === 'the entry script without the security headers' &&
        path === SCRIPT);
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
        if (bare(status)) continue;
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

    const head =
      fault === 'the entry script retyped (Rocket Loader)'
        ? ENTRY.replace('type="module"', 'type="0f1e2d3c-module"') + STYLES
        : fault === 'index.html without its stylesheet'
          ? ENTRY
          : ENTRY + STYLES;
    const html =
      fault === 'nginx’s welcome page everywhere' ? WELCOME : page(head);
    const index = () =>
      request.get('If-None-Match') === '"v1"' &&
      fault !== 'If-None-Match ignored'
        ? send(304, null, { 'Cache-Control': 'no-cache', ETag: '"v1"' })
        : send(200, html, {
            'Content-Type':
              fault === 'index.html as text'
                ? 'text/plain'
                : 'text/html; charset=utf-8',
            'Cache-Control':
              fault === 'index.html is cached' ||
              (fault === 'a page path cached an hour' &&
                path === '/programs/cs-ms')
                ? 'max-age=3600'
                : 'no-cache',
            ...(fault === 'no ETag' ? {} : { ETag: '"v1"' }),
          });

    if (method === 'POST')
      return fault === 'a large body is a 413' && bodySize > 1024 * 1024
        ? send(
            413,
            '<html><body>413 Request Entity Too Large</body></html>',
            {},
          )
        : send(405, '<html><body>405 Not Allowed</body></html>', {
            'Cache-Control': 'no-cache',
          });
    if (path === MALFORMED && fault !== 'a malformed request is the page')
      return send(400, '<html><body>400 Bad Request</body></html>', {});
    if (path === '/' && fault === 'index.html behind a redirect')
      return send(301, null, { Location: `${SITE}/index.html` });
    if (path === '/healthz')
      return send(200, fault === 'the health check says OK' ? 'OK' : 'ok\n', {
        'Content-Type':
          fault === 'the health check as bytes'
            ? 'application/octet-stream'
            : 'text/plain; charset=utf-8',
        'Cache-Control':
          fault === 'the health check is cached' ? 'max-age=60' : 'no-store',
      });
    if (path === '/favicon.svg')
      return fault === 'the icon is index.html'
        ? index()
        : send(200, '<svg xmlns="http://www.w3.org/2000/svg"></svg>', {
            'Content-Type':
              fault === 'the icon as text' ? 'text/plain' : 'image/svg+xml',
            'Cache-Control':
              fault === 'the icon cached for a year' ? IMMUTABLE : 'no-cache',
          });
    if (path === SCRIPT) {
      if (fault === 'the entry script is a 404')
        return send(404, '<html><body>404 Not Found</body></html>', {});
      const api =
        fault === 'a bundle built for another API'
          ? 'https://api.example.test'
          : API;
      const share =
        fault === 'a bundle whose links name compass'
          ? 'https://compass.neu-compass.me'
          : SHARE;
      return send(200, `const api = "${api}", site = "${share}";`, {
        'Content-Type':
          fault === 'a JavaScript file as text'
            ? 'text/plain'
            : 'application/javascript; charset=utf-8',
        'Cache-Control':
          fault === 'assets are not cached' ? 'no-cache' : IMMUTABLE,
      });
    }
    if (path === STYLESHEET)
      return send(200, 'body{margin:0}', {
        'Content-Type':
          fault === 'a stylesheet as text' ? 'text/plain' : 'text/css',
        'Cache-Control': IMMUTABLE,
      });
    if (path.startsWith('/assets/')) {
      if (fault === 'a missing chunk is index.html') return index();
      if (fault === 'a missing chunk is an empty 200') return send(200, '', {});
      if (fault === 'a missing chunk is a 404 with index.html (error_page)')
        return send(404, html, {});
      return send(
        404,
        '<html><body>404 Not Found</body></html>',
        fault === 'a missing chunk is cached for a year'
          ? { 'Cache-Control': IMMUTABLE }
          : {},
      );
    }
    if (
      path === '/assets' &&
      fault === '/assets redirected to /assets/ (try_files $uri/)'
    )
      return send(301, '<html><body>301 Moved Permanently</body></html>', {
        Location: `${SITE}/assets/`,
      });
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
    const method = init?.method ?? 'GET';
    requested.push(
      method === 'GET' ? target.pathname : `${method} ${target.pathname}`,
    );
    const body = init?.body;
    return site(
      target.pathname,
      new Headers(init?.headers),
      method,
      body instanceof Uint8Array ? body.byteLength : 0,
    );
  });
  const failures = await checkSite(SITE, API, SHARE);
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
      STYLESHEET,
      MISSING,
      '/',
      'POST /course/CS-6140',
      MALFORMED,
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
