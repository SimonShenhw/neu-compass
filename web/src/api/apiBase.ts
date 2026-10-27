// Where the API is (R2b). Fixed when the bundle is built, from VITE_API_BASE_URL, and never worked out from the page's
// own address: vite.config.ts calls chooseApiBase and hands the result to the code as __API_BASE_URL__.
export const PRODUCTION_API = 'https://api.neu-compass.me';
// 127.0.0.1, like the dev server: the page and the API must share a host name, or the browser treats them as two
// sites and never sends the SameSite=Lax session cookie along with a request.
export const LOCAL_API = 'http://127.0.0.1:8000';

const LOCAL_HOSTS = new Set(['localhost', '127.0.0.1', '[::1]']);

// An https origin, or plain http on this machine only; no path, query, fragment or credentials, because every
// request path is appended to it. A bad value stops the build instead of shipping a page that calls the wrong place.
export function apiBaseUrl(
  value: string | undefined,
  fallback: string,
  name = 'VITE_API_BASE_URL',
): string {
  const raw = value?.trim() || fallback;
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new Error(`${name} is not a URL.`);
  }
  const local = url.protocol === 'http:' && LOCAL_HOSTS.has(url.hostname);
  if (
    (url.protocol !== 'https:' && !local) ||
    url.username ||
    url.password ||
    url.pathname !== '/' ||
    url.search ||
    url.hash
  )
    throw new Error(
      `${name} must be an https origin (or http://localhost) with nothing after the host and port.`,
    );
  return url.origin;
}

// The build mode of `npm run build:dev-api`: a bundle for this machine, to preview against the dev API.
export const DEV_API_MODE = 'dev-api';

// Which API a bundle talks to.
// - A production build (`npm run build`): the production API, or another https one VITE_API_BASE_URL names; never plain
//   http, so no bundle meant for students calls their own machine.
// - `npm run build:dev-api` and the dev server: this machine's API, unless VITE_API_BASE_URL names another.
// - Any other build mode (a beta, say) must name its API.
// - The tests always use this machine's, whatever the environment says.
export function chooseApiBase(
  command: 'build' | 'serve',
  mode: string,
  value: string | undefined,
): string {
  if (command === 'serve')
    return mode === 'test' ? LOCAL_API : apiBaseUrl(value, LOCAL_API);
  if (mode === 'production') {
    const base = apiBaseUrl(value, PRODUCTION_API);
    if (!base.startsWith('https:'))
      throw new Error(
        'A production build needs an https API; npm run build:dev-api builds for the API on this machine.',
      );
    return base;
  }
  if (mode === DEV_API_MODE) return apiBaseUrl(value, LOCAL_API);
  if (!value?.trim())
    throw new Error(`A build in mode "${mode}" needs VITE_API_BASE_URL.`);
  return apiBaseUrl(value, PRODUCTION_API);
}

// The site a shared link points at (R3e; R0 16.4), fixed at build time like the API's address and never the page's
// own address: a link shared from a beta is still the production site's, as Streamlit's PUBLIC_BASE_URL is.
export const PRODUCTION_SITE = 'https://compass.neu-compass.me';
// The dev server's port: VITE_DEV_PORT when 5173 is taken (Windows can reserve it), else 5173. The dev API is told the
// same port (tests/support/dev_api.py --web-port), so its CORS and sign-in accept the page.
export const DEV_PORT = 5173;
export const PREVIEW_PORT = 4173;

export function devPort(value: string | undefined): number {
  const text = value?.trim() ?? '';
  if (text === '') return DEV_PORT;
  const port = /^[0-9]{4,5}$/.test(text) ? Number(text) : NaN;
  if (!(port >= 1024 && port <= 65535))
    throw new Error('VITE_DEV_PORT must be a port from 1024 to 65535.');
  return port;
}

// Which site a bundle's shared links name: the production site for every build meant for students, a beta included,
// unless VITE_PUBLIC_BASE_URL names another https one; this machine's dev server or preview for the dev server and
// `npm run build:dev-api`; the tests always the dev server's.
export function choosePublicBase(
  command: 'build' | 'serve',
  mode: string,
  value: string | undefined,
  port: number,
): string {
  const name = 'VITE_PUBLIC_BASE_URL';
  if (command === 'serve')
    return mode === 'test'
      ? `http://127.0.0.1:${DEV_PORT}`
      : apiBaseUrl(value, `http://127.0.0.1:${port}`, name);
  if (mode === DEV_API_MODE)
    return apiBaseUrl(value, `http://127.0.0.1:${PREVIEW_PORT}`, name);
  const base = apiBaseUrl(value, PRODUCTION_SITE, name);
  if (!base.startsWith('https:'))
    throw new Error(
      'A shared link must name an https site; npm run build:dev-api builds for this machine.',
    );
  return base;
}
