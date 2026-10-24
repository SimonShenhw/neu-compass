import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { gzipSync } from 'node:zlib';

// The build to measure: dist/ by default, dist-dev-api/ for npm run build:dev-api.
const dir = process.argv[2] ?? 'dist';
const manifest = JSON.parse(
  readFileSync(resolve(dir, '.vite/manifest.json'), 'utf8'),
);
const files = new Set();
const visited = new Set();
function collect(key) {
  if (visited.has(key)) return;
  visited.add(key);
  const chunk = manifest[key];
  if (!chunk) throw new Error(`Manifest entry is missing: ${key}`);
  if (chunk.file.endsWith('.js')) files.add(chunk.file);
  for (const imported of chunk.imports ?? []) collect(imported);
}
for (const [key, chunk] of Object.entries(manifest))
  if (chunk.isEntry) collect(key);
if (!files.size) throw new Error('No entry JavaScript was measured');
const compressed = [...files].reduce(
  (total, file) =>
    total + gzipSync(readFileSync(resolve(dir, file))).byteLength,
  0,
);
console.info(
  `Initial JavaScript gzip: ${compressed} bytes / 250000 bytes (${files.size} files)`,
);
if (compressed > 250000)
  throw new Error('Initial JavaScript exceeds the 250 KB gzip budget');
