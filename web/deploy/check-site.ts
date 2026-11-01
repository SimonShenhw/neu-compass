// R7: what the web image serves, checked from outside as a browser and Cloudflare see it. CI runs it against the web
// service compose starts (the web-image job); so can anyone against a running one (Node 24 runs TypeScript as it is):
//   node deploy/check-site.ts http://127.0.0.1:8510 https://api.neu-compass.me
// Every kind of response, a page, a file, a 404, a 304 and the health check, carries exactly the security headers of a
// build for that API; every page path is index.html; only /assets/ is cached for good; the build's .vite/ is not served.
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { securityHeaders } from './securityHeaders.ts';

type Fetched = { status: number; headers: Headers; body: string };

// Paths a browser may open that are no file of the build: each is the app's index.html.
const PAGE_PATHS = [
  '/index.html',
  '/course/CS-6140',
  '/programs/cs-ms',
  '/assets',
  '/.vite/manifest.json',
  '/.vite/security-headers.json',
];
const MISSING_ASSET = '/assets/no-such-chunk-0000.js';

export async function checkSite(site: string, api: string): Promise<string[]> {
  const failures: string[] = [];
  const expected = securityHeaders(api);
  const check = (ok: boolean, failure: string) => {
    if (!ok) failures.push(failure);
  };
  async function get(path: string, headers: Record<string, string> = {}) {
    const response = await fetch(new URL(path, site), {
      headers,
      redirect: 'manual',
    });
    return {
      status: response.status,
      headers: response.headers,
      body: await response.text(),
    } satisfies Fetched;
  }
  function header(
    path: string,
    response: Fetched,
    name: string,
    value: string | null,
  ) {
    const sent = response.headers.get(name);
    check(
      sent === value,
      `${path}: ${name} is ${JSON.stringify(sent)}, not ${JSON.stringify(value)}`,
    );
  }
  function secured(path: string, response: Fetched) {
    for (const [name, value] of Object.entries(expected))
      header(path, response, name, value);
    // server_tokens off: no version.
    header(path, response, 'Server', 'nginx');
  }

  const health = await get('/healthz');
  check(
    health.status === 200 && health.body === 'ok\n',
    `/healthz: ${health.status} ${JSON.stringify(health.body)}`,
  );
  header('/healthz', health, 'Cache-Control', 'no-store');
  secured('/healthz', health);

  const index = await get('/');
  check(index.status === 200, `/: ${index.status}`);
  check(
    index.body.includes('<div id="root"></div>'),
    "/: not the app's index.html",
  );
  header('/', index, 'Content-Type', 'text/html; charset=utf-8');
  header('/', index, 'Cache-Control', 'no-cache');
  secured('/', index);
  const script =
    /<script type="module" crossorigin src="(\/assets\/[^"]+\.js)">/.exec(
      index.body,
    )?.[1];
  check(Boolean(script), '/: no module script under /assets/');

  for (const path of PAGE_PATHS) {
    const page = await get(path);
    check(
      page.status === 200 && page.body === index.body,
      `${path}: ${page.status}, not the app's index.html`,
    );
    header(path, page, 'Cache-Control', 'no-cache');
    secured(path, page);
  }

  const icon = await get('/favicon.svg');
  check(
    icon.status === 200 && icon.body.startsWith('<svg '),
    `/favicon.svg: ${icon.status}`,
  );
  header('/favicon.svg', icon, 'Content-Type', 'image/svg+xml');
  header('/favicon.svg', icon, 'Cache-Control', 'no-cache');
  secured('/favicon.svg', icon);

  if (script) {
    const asset = await get(script);
    check(asset.status === 200, `${script}: ${asset.status}`);
    header(
      script,
      asset,
      'Content-Type',
      'application/javascript; charset=utf-8',
    );
    header(
      script,
      asset,
      'Cache-Control',
      'public, max-age=31536000, immutable',
    );
    secured(script, asset);
  }

  // A chunk a page left open across a deploy asks for: a plain 404, not index.html, and not cached for a year.
  const missing = await get(MISSING_ASSET);
  check(
    missing.status === 404 && !missing.body.includes('<div id="root">'),
    `${MISSING_ASSET}: ${missing.status}, not a plain 404`,
  );
  header(MISSING_ASSET, missing, 'Cache-Control', null);
  secured(MISSING_ASSET, missing);

  // A browser revalidating its copy of index.html.
  const etag = index.headers.get('ETag');
  check(Boolean(etag), '/: no ETag');
  if (etag) {
    const again = await get('/', { 'If-None-Match': etag });
    check(
      again.status === 304,
      `/ with If-None-Match: ${again.status}, not 304`,
    );
    secured('/ with If-None-Match', again);
  }
  return failures;
}

if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  const [site, api] = process.argv.slice(2);
  if (!site || !api)
    throw new Error('Usage: node deploy/check-site.ts <site> <API origin>');
  const failures = await checkSite(site, api);
  for (const failure of failures) console.error(failure);
  console.info(
    failures.length
      ? `${failures.length} checks failed at ${site}.`
      : `${site} serves the site as it should, for ${api}.`,
  );
  process.exitCode = failures.length ? 1 : 0;
}
