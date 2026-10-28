import { createHash } from 'node:crypto';
import {
  cpSync,
  existsSync,
  lstatSync,
  readFileSync,
  writeFileSync,
  readdirSync,
  mkdirSync,
  mkdtempSync,
  realpathSync,
  rmSync,
  symlinkSync,
  unlinkSync,
} from 'node:fs';
import { join, resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { spawnSync } from 'node:child_process';

const root = process.cwd();
if (JSON.parse(readFileSync('package.json', 'utf8')).name !== 'neu-compass-web')
  throw Error('Run from web/');
const config = [
  'package.json',
  'package-lock.json',
  'tsconfig.json',
  'vite.config.ts',
  'eslint.config.js',
  '.prettierrc',
  'index.html',
  'openapi.json',
  'tools/openapi-types/package.json',
  'tools/openapi-types/package-lock.json',
  'tools/openapi-types/generate.mjs',
];
const paths = (dir) =>
  readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? paths(join(dir, e.name)) : [join(dir, e.name)],
  );
const hash = (f) => createHash('sha256').update(readFileSync(f)).digest('hex');
const freeze = () =>
  Object.fromEntries(
    [
      ...paths(join(root, 'src')),
      ...paths(join(root, 'scripts')),
      ...config.map((f) => join(root, f)),
    ].map((f) => [f, hash(f)]),
  );
const frozen = freeze(),
  output = join(
    root,
    'artifacts',
    'landing-mutations-' + new Date().toISOString().replaceAll(/[:.]/g, '-'),
  );
mkdirSync(output, { recursive: true });
const snapshot = mkdtempSync(
  join(realpathSync.native(tmpdir()), 'neu-landing-'),
);
// The copy goes when the process exits, a failed baseline or a bad anchor included. Its junctions go first, so removing
// it cannot reach the node_modules behind them; if one cannot be removed, the copy stays. There is no signal handler:
// the run is synchronous, so one would only run after the last mutant, and Ctrl+C would no longer stop the run (R4c,
// as in draft-mutations.mjs).
process.on('exit', () => {
  const links = ['node_modules', 'tools/openapi-types/node_modules'].map((l) =>
    join(snapshot, l),
  );
  for (const link of links)
    if (lstatSync(link, { throwIfNoEntry: false })?.isSymbolicLink())
      try {
        unlinkSync(link);
      } catch {
        // The next link is still tried; the check below keeps the copy and says where it is.
      }
  if (links.some((link) => existsSync(link)))
    console.error('Copy kept, a link is still there: ' + snapshot);
  else rmSync(snapshot, { recursive: true, force: true });
});
cpSync(join(root, 'src'), join(snapshot, 'src'), { recursive: true });
for (const file of config) {
  const target = join(snapshot, file);
  mkdirSync(join(target, '..'), { recursive: true });
  cpSync(join(root, file), target);
}
symlinkSync(
  resolve(root, 'node_modules'),
  join(snapshot, 'node_modules'),
  process.platform === 'win32' ? 'junction' : 'dir',
);
symlinkSync(
  resolve(root, 'tools/openapi-types/node_modules'),
  join(snapshot, 'tools/openapi-types/node_modules'),
  process.platform === 'win32' ? 'junction' : 'dir',
);
const vitest = join(root, 'node_modules/vitest/vitest.mjs'),
  tsc = join(root, 'node_modules/typescript/bin/tsc');
function run(args, name, timeout = 45000) {
  const r = spawnSync(process.execPath, args, {
    cwd: snapshot,
    encoding: 'utf8',
    timeout,
    maxBuffer: 8 * 1024 * 1024,
    windowsHide: true,
  });
  writeFileSync(
    join(output, name + '.log'),
    (r.stdout ?? '') + (r.stderr ?? '') + (r.error?.message ?? ''),
  );
  return r;
}
console.info('Evidence: ' + output);
if (
  run([tsc, '--noEmit', '--pretty', 'false'], 'baseline-types').status !== 0 ||
  run([vitest, 'run'], 'baseline-tests', 90000).status !== 0
)
  throw Error('Snapshot baseline failed');
const cases = [];
function add(label, file, from, to, test, expected, mode = 'test') {
  cases.push({
    id: 'L' + String(cases.length + 1).padStart(2, '0'),
    label,
    file,
    from,
    to,
    test,
    expected,
    mode,
  });
}
const model = 'src/models/landing.ts',
  ui = 'src/features/search-landing/SearchLanding.tsx',
  core = 'src/models/landing.test.ts',
  view = 'src/features/search-landing/SearchLanding.test.tsx',
  demo = 'src/pages/SearchLandingDemoPage.test.tsx';
add(
  'only semester one',
  model,
  'group.semester !== 1',
  'group.semester < 1',
  core,
  'semester1 reference',
);
add(
  'core or foundation only',
  model,
  "c.requirement_type === 'foundation'",
  "c.requirement_type === 'elective_pool'",
  core,
  'semester1 reference',
);
add(
  'later semester-one groups still searched',
  model,
  'if (pick) return pick;',
  'return pick ?? null;',
  core,
  'semester1 reference',
);
add(
  'featured program order',
  model,
  "['aai-ms', 'cs-ms', 'ds-ms']",
  "['cs-ms', 'aai-ms', 'ds-ms']",
  view,
  'landing golden',
);
add(
  'featured program must be listed',
  model,
  'rows.some((p) => p.program_id === id)',
  'true',
  view,
  'landing golden aai-not-listed',
);
add(
  'curriculum prefix wins',
  model,
  'prefix: c.data.prefix',
  'prefix: rows.find(p => p.program_id === id)!.prefix',
  view,
  'landing golden cs-curriculum-text-edge',
);
add(
  'empty interview is missing',
  model,
  '!row.interview_summary',
  'row.interview_summary === null',
  core,
  'Co-op lock reference',
);
add(
  'zero level never locks',
  model,
  'row.visibility_level === 1',
  'row.visibility_level <= 1',
  core,
  'Co-op lock reference',
);
add(
  'only first two Co-op rows inspected',
  'src/models/coopPreview.ts',
  'value.slice(0, 2)',
  'value.slice(0, 3)',
  core,
  'Co-op preview defaults optional strings',
);
add(
  'plain failures are transient via adapter',
  'src/api/load.ts',
  'isTransientError(new ApiError(failure.status, failure))',
  'isTransientError(failure)',
  core,
  'transient reference',
);
add(
  'definite failures do not retry',
  'src/api/load.ts',
  'isTransientError(new ApiError(failure.status, failure))',
  'failure.status >= 400',
  core,
  'transient reference',
);
add(
  'all temporary statuses included',
  'src/api/load.ts',
  'isTransientError(new ApiError(failure.status, failure))',
  'failure.status === 503',
  core,
  'transient reference',
);
add(
  'starters wait for every relevant curriculum',
  model,
  "const starters = entries.some((e) => e.load.status === 'loading')",
  'const starters = false',
  view,
  'loading',
);
add(
  'missing curriculum stays loading',
  model,
  'curricula[id]! : loading',
  "curricula[id]! : { status: 'ready' as const, data: null }",
  view,
  'a missing required curriculum',
);
add(
  'program failure ignores dependent pending',
  model,
  "entries.some((e) => e.load.status === 'loading');",
  "Object.values(curricula).some(e => e.status === 'loading');",
  view,
  'definite failure',
);
add(
  'one retry notice for multiple failures',
  ui,
  '部分内容暂时没加载出来。',
  '部分内容暂时没加载出来。部分内容暂时没加载出来。',
  view,
  'a missing required curriculum',
);
add(
  'sample sends query not label',
  ui,
  'props.onAsk(q.query)',
  'props.onAsk(q.label)',
  view,
  'each landing button',
);
add(
  'any existing turn hides landing',
  model,
  'turns.length === 0',
  "turns.every(t => t.text === '')",
  core,
  'landing visibility',
);
add(
  'conversation receives focus',
  'src/features/search-landing/LandingConversation.tsx',
  'if (hasConversation) region.current?.focus({ preventScroll: true });',
  'if (false) region.current?.focus({ preventScroll: true });',
  demo,
  'sample',
);
add(
  'read source delay remains 300ms',
  'src/features/search-landing/useLandingDemo.ts',
  'later(300, () => {',
  'later(301, () => {',
  demo,
  'demo sources release',
);
add(
  'unmount cancels every read timer',
  'src/features/search-landing/useLandingDemo.ts',
  'for (const timer of timers) clearTimeout(timer);',
  'for (const timer of []) clearTimeout(timer);',
  demo,
  'slow multiplies',
);
add(
  'scenario changes rebuild the session',
  'src/pages/SearchLandingDemoPage.tsx',
  'key={`${options.scenario}:${options.speed}:${replay}`}',
  'key={replay}',
  demo,
  'scenario and speed changes',
);
add(
  'program duplicate IDs invalid',
  'src/models/programs.ts',
  'new Set(rows.map((r) => r.program_id)).size === rows.length',
  'true',
  core,
  'program list rejects duplicate IDs',
);
add(
  'curriculum identity checked',
  'src/models/programs.ts',
  'value.program_id !== programId',
  'false',
  core,
  'curriculum checks every',
);
add(
  'semester has upper bound eight',
  'src/models/programs.ts',
  'integer(v.semester, 1, 8)',
  'integer(v.semester, 1, 9)',
  core,
  'curriculum checks every',
);
add(
  'course IDs cannot be empty',
  'src/models/programs.ts',
  "v.course_id === ''",
  'false',
  core,
  'curriculum checks every',
);
add(
  'plain text drops CR only',
  model,
  "text.replaceAll('\\r', '')",
  'text',
  core,
  'landing plain text',
);
add(
  'compile-time scalar schema drift',
  'src/api/programs.ts',
  'plan_count: number;',
  'plan_count: boolean;',
  null,
  'src/api/programs.types.test.ts',
  'types',
);
add(
  'compile-time nested course drift',
  'src/api/programs.ts',
  'primary_name: string;',
  'primary_name: number;',
  null,
  'src/api/programs.types.test.ts',
  'types',
);
const results = [];
for (const c of cases) {
  const file = join(snapshot, c.file),
    original = readFileSync(file, 'utf8');
  if (original.split(c.from).length !== 2)
    throw Error(c.id + ': expected one mutation anchor');
  const changed = original.replace(c.from, c.to),
    report = join(output, c.id + '.json');
  writeFileSync(file, changed);
  let r;
  try {
    r = run(
      c.mode === 'types'
        ? [tsc, '--noEmit', '--pretty', 'false']
        : [
            vitest,
            'run',
            c.test,
            '-t',
            c.expected,
            '--reporter=json',
            '--outputFile',
            report,
          ],
      c.id,
    );
  } finally {
    writeFileSync(file, original);
  }
  let failures = [];
  if (c.mode === 'types')
    failures = ((r.stdout ?? '') + (r.stderr ?? ''))
      .split('\n')
      .filter(
        (l) =>
          l.replaceAll('\\', '/').includes(c.expected) &&
          l.includes('error TS2349') &&
          ((r.stdout ?? '') + (r.stderr ?? '')).includes(
            `ExpectNever<"${c.from.split(':')[0]}">`,
          ),
      );
  else
    try {
      failures = JSON.parse(readFileSync(report, 'utf8')).testResults.flatMap(
        (s) =>
          s.assertionResults
            .filter((a) => a.status === 'failed')
            .map((a) => a.fullName),
      );
    } catch {
      /* Missing reports never count as kills. */
    }
  const killed =
    !r.error &&
    (c.mode === 'types'
      ? r.status === 2 && failures.length > 0
      : r.status === 1 && failures.some((n) => n.includes(c.expected)));
  results.push({
    ...c,
    killed,
    exitCode: r.status,
    failures,
    mutatedSha256: createHash('sha256').update(changed).digest('hex'),
  });
  console.info(
    c.id + ' ' + (killed ? 'KILLED' : 'UNRESOLVED') + ': ' + c.label,
  );
}
const sourceUnchanged = JSON.stringify(frozen) === JSON.stringify(freeze());
writeFileSync(
  join(output, 'summary.json'),
  JSON.stringify(
    { baseline: 'passed', snapshot, frozen, sourceUnchanged, results },
    null,
    2,
  ),
  { flag: 'wx' },
);
if (!sourceUnchanged || results.some((r) => !r.killed)) process.exitCode = 1;
