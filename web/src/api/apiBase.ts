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
): string {
  const raw = value?.trim() || fallback;
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new Error('VITE_API_BASE_URL is not a URL.');
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
      'VITE_API_BASE_URL must be an https origin (or http://localhost) with nothing after the host and port.',
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
