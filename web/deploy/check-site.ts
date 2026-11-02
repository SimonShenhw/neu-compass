// R7: what the web image serves, checked from outside as a browser sees it. CI runs it against the web service compose
// starts (the web-image job); so can anyone against a running one (Node 24 runs TypeScript as it is), on the NAS's port:
//   node deploy/check-site.ts http://127.0.0.1:8510 https://api.neu-compass.me https://beta.neu-compass.me
// The service itself, not the site through Cloudflare, which names itself in Server and may add caching headers.
// Every kind of response, a page, a file, a 404, a 304, a 405, nginx's own 400 and the health check, carries exactly
// the security headers of a build for that API; every page path is index.html; only /assets/ is cached for good; the
// build's .vite/ is not served; a body is never refused for its size (nginx would log that request's line); and the
// bundle was built for that API and for the site its shared links are to name.
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { securityHeaders } from './securityHeaders.ts';

type Fetched = { status: number; headers: Headers; body: string };

// Paths a browser may open, each answered with the app's index.html: the file itself, and paths that are no file of
// the build (a page, /assets without its slash, what the build's .vite/ held).
const PAGE_PATHS = [
  '/index.html',
  '/course/CS-6140',
  '/programs/cs-ms',
  '/assets',
  '/.vite/manifest.json',
  '/.vite/security-headers.json',
];
const MISSING_ASSET = '/assets/no-such-chunk-0000.js';
// More than nginx's default client_max_body_size of 1 MiB.
const LARGE_BODY = 1_100_000;
// An escape nginx cannot decode: it answers 400 itself, before any location.
const MALFORMED = '/course/%zz';

export async function checkSite(
  site: string,
  api: string,
  share: string,
): Promise<string[]> {
  const failures: string[] = [];
  const expected = securityHeaders(api);
  const check = (ok: boolean, failure: string) => {
    if (!ok) failures.push(failure);
  };
  async function get(path: string, init: RequestInit = {}) {
    const response = await fetch(new URL(path, site), {
      ...init,
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

  // deploy.ps1 reads the body as text, which PowerShell gives it only for a text type.
  const health = await get('/healthz');
  check(
    health.status === 200 && health.body === 'ok\n',
    `/healthz: ${health.status} ${JSON.stringify(health.body)}`,
  );
  header('/healthz', health, 'Content-Type', 'text/plain; charset=utf-8');
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
  const stylesheet =
    /<link rel="stylesheet" crossorigin href="(\/assets\/[^"]+\.css)">/.exec(
      index.body,
    )?.[1];
  check(Boolean(stylesheet), '/: no stylesheet under /assets/');

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
    `/favicon.svg: ${icon.status}, not the icon`,
  );
  header('/favicon.svg', icon, 'Content-Type', 'image/svg+xml');
  header('/favicon.svg', icon, 'Cache-Control', 'no-cache');
  secured('/favicon.svg', icon);

  // The built files, each with the type a browser takes it as under nosniff, cached for good.
  for (const [file, type] of [
    [script, 'application/javascript; charset=utf-8'],
    [stylesheet, 'text/css'],
  ] as const) {
    if (!file) continue;
    const asset = await get(file);
    check(asset.status === 200, `${file}: ${asset.status}`);
    header(file, asset, 'Content-Type', type);
    header(file, asset, 'Cache-Control', 'public, max-age=31536000, immutable');
    secured(file, asset);
    // The bundle calls the API the policy names, and its shared links name the site they are meant to.
    if (file === script) {
      check(asset.body.includes(api), `${file}: no ${api} in the bundle`);
      check(asset.body.includes(share), `${file}: no ${share} in the bundle`);
    }
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
    const again = await get('/', { headers: { 'If-None-Match': etag } });
    check(
      again.status === 304,
      `/ with If-None-Match: ${again.status}, not 304`,
    );
    secured('/ with If-None-Match', again);
  }

  // A body nothing here reads is thrown away, whatever its size: a POST is a 405, never a 413.
  const posted = await get('/course/CS-6140', {
    method: 'POST',
    body: new Uint8Array(LARGE_BODY),
  });
  check(
    posted.status === 405,
    `POST /course/CS-6140 with ${LARGE_BODY} bytes: ${posted.status}, not 405`,
  );
  secured('POST /course/CS-6140', posted);

  // What nginx answers by itself, before any location, carries the headers too.
  const malformed = await get(MALFORMED);
  check(malformed.status === 400, `${MALFORMED}: ${malformed.status}, not 400`);
  secured(MALFORMED, malformed);
  return failures;
}

if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  const [site, api, share] = process.argv.slice(2);
  if (!site || !api || !share)
    throw new Error(
      'Usage: node deploy/check-site.ts <site> <API origin> <the site shared links name>',
    );
  const failures = await checkSite(site, api, share);
  for (const failure of failures) console.error(failure);
  console.info(
    failures.length
      ? `${failures.length} checks failed at ${site}.`
      : `${site} serves the site as it should, for ${api}, its links to ${share}.`,
  );
  process.exitCode = failures.length ? 1 : 0;
}
