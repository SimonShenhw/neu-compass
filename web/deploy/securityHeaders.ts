// R7: the headers every response of the site carries, wherever it is served from: nginx in the web image (each
// location of deploy/nginx.conf includes them, as deploy/render-headers.mjs writes them) and vite preview, which the
// end-to-end tests use. A build writes them for the API it calls to .vite/security-headers.json (vite.config.ts), and
// both send that file's headers, so the policy a page runs under is the one its build was made with.
export function securityHeaders(apiBase: string): Record<string, string> {
  // An origin only, as src/api/apiBase.ts has made it: nothing else reaches the policy.
  if (new URL(apiBase).origin !== apiBase)
    throw new Error(`Not an origin: ${apiBase}`);
  return {
    'Content-Security-Policy': [
      "default-src 'none'",
      "script-src 'self'",
      // While a dialog or a select is open, Radix adds a <style> of its own (react-remove-scroll-bar), with no nonce.
      "style-src 'self' 'unsafe-inline'",
      "img-src 'self'",
      "font-src 'self'",
      // The API; and the site, from which Vite's module preload polyfill fetches chunks in a browser without
      // modulepreload.
      `connect-src 'self' ${apiBase}`,
      "base-uri 'none'",
      "form-action 'none'",
      "frame-ancestors 'none'",
    ].join('; '),
    // index.html says so too (R0 14.15); the header covers every response.
    'Referrer-Policy': 'strict-origin-when-cross-origin',
    'X-Content-Type-Options': 'nosniff',
  };
}
