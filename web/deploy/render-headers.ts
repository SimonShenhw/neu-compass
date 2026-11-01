// R7: the build's security headers (.vite/security-headers.json, from deploy/securityHeaders.ts) as the add_header lines
// that every location of deploy/nginx.conf includes. The web image's build stage runs it (web/Dockerfile; Node 24 runs
// TypeScript as it is):
//   node deploy/render-headers.ts dist/.vite/security-headers.json > security-headers.conf
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export function renderHeaders(headers: unknown): string {
  if (typeof headers !== 'object' || headers === null || Array.isArray(headers))
    throw new Error('The headers are not an object.');
  const entries = Object.entries(headers);
  if (!entries.length) throw new Error('There are no headers.');
  return entries
    .map(([name, value]) => {
      if (!/^[A-Za-z][A-Za-z0-9-]*$/.test(name))
        throw new Error(`Not a header name: ${JSON.stringify(name)}`);
      // Printable ASCII on one line; nginx would read $ as a variable, and a quote or a backslash ends or escapes
      // the string.
      if (
        typeof value !== 'string' ||
        !/^[\x20-\x7e]+$/.test(value) ||
        /["\\$]/.test(value)
      )
        throw new Error(`The value of ${name} cannot be written for nginx.`);
      return `add_header ${name} "${value}" always;\n`;
    })
    .join('');
}

if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  const [file] = process.argv.slice(2);
  if (!file)
    throw new Error(
      'Usage: node deploy/render-headers.ts <security-headers.json>',
    );
  process.stdout.write(renderHeaders(JSON.parse(readFileSync(file, 'utf8'))));
}
