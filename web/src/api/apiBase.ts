// Where the API is (R2b). Fixed when the bundle is built, from VITE_API_BASE_URL, and never worked out from the page's
// own address: vite.config.ts calls this and hands the result to the code as __API_BASE_URL__.
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
