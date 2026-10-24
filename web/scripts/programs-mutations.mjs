import { createHash } from 'node:crypto';
import {
  cpSync,
  readFileSync,
  writeFileSync,
  readdirSync,
  mkdirSync,
  mkdtempSync,
  realpathSync,
  symlinkSync,
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
    'programs-mutations-' + new Date().toISOString().replaceAll(/[:.]/g, '-'),
  );
mkdirSync(output, { recursive: true });
const snapshot = mkdtempSync(
  join(realpathSync.native(tmpdir()), 'neu-programs-'),
);
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
const cases = [];
function add(label, file, from, to, test, expected, mode = 'test') {
  cases.push({
    id: 'P' + String(cases.length + 1).padStart(2, '0'),
    label,
    file,
    from,
    to,
    test,
    expected,
    mode,
  });
}
const core = 'src/models/programPlans.test.tsx',
  format = 'src/models/programFormat.test.tsx',
  view = 'src/features/programs/Programs.test.tsx',
  demo = 'src/pages/ProgramsDemoPage.test.tsx';
const plans = 'src/models/programPlans.ts',
  policy = 'src/models/programPolicy.ts',
  formats = 'src/models/programFormat.ts',
  ui = 'src/features/programs/ProgramCurriculum.tsx',
  policies = 'src/features/programs/ProgramPolicies.tsx';
add(
  'complete rejects unmodeled',
  plans,
  'unmodeled(value.requirements)',
  'false',
  core,
  'complete plans reject',
);
add(
  'foreign plan excluded',
  plans,
  'value.program_id !== programId',
  'false',
  view,
  'cs-foreign-plan matches',
);
add(
  'all ambiguous IDs excluded',
  plans,
  'ids.get(p.plan_id) === 1',
  'true',
  core,
  'duplicate IDs and scopes',
);
add(
  'all ambiguous scopes excluded',
  plans,
  'scopes.get(scopeKey(p)) === 1',
  'true',
  core,
  'duplicate IDs and scopes',
);
add(
  'Python whitespace differs from JS',
  formats,
  '/[\\u0009-\\u000d\\u001c-\\u0020\\u0085\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000]+/',
  '/\\s+/',
  format,
  'whitespace vector',
);
add(
  'capture Z uses isoformat',
  formats,
  "text.replace(/Z$/, '+00:00')",
  'text',
  format,
  'small formatting helpers',
);
add(
  'strip all base slashes',
  formats,
  "base.replace(/\\/+$/, '')",
  "base.replace(/\\/$/, '')",
  format,
  'share URL vector',
);
add(
  'concentration null stays JSON null',
  formats,
  'JSON.stringify(link.concentration)',
  "JSON.stringify(link.concentration ?? '')",
  format,
  'share URL vector',
);
add(
  'Python quote_plus preserves tilde',
  formats,
  'return encodeURIComponent(text)',
  "return new URLSearchParams([['x', text]]).toString().slice(2)",
  format,
  'share URL vector',
);
add(
  'unknown badge uses foundation',
  formats,
  "labels.get(type) ?? '基础 · foundation'",
  "labels.get(type) ?? '核心 · core'",
  format,
  'small formatting helpers',
);
add(
  'single plan never selected automatically',
  ui,
  'plans.find((p) => p.plan_id === props.selectedPlanId)',
  'plans.find((p) => p.plan_id === props.selectedPlanId) ?? plans[0]',
  view,
  'select is controlled',
);
add(
  'draft never gets precise share',
  ui,
  "plan?.review_status === 'source_checked' && hash(revision)",
  'plan && hash(revision)',
  view,
  'cs-bridge-draft matches',
);
add(
  'scope concentration whitespace collapsed only in description',
  ui,
  'collapseSpace(plan.concentration)',
  'plan.concentration',
  view,
  'cs-text-edge matches',
);
add(
  'option does not include program id',
  ui,
  'label: scopeLabel(p)',
  'label: p.program_id + scopeLabel(p)',
  view,
  'cs-nothing-selected matches',
);
add(
  'policy version must match',
  policies,
  'view.plan_content_sha256 !== revision',
  'false',
  view,
  'cs-standard-policies-other-revision matches',
);
add(
  'missing revision never displays ready evidence',
  policies,
  '!hash(revision) ||\n    view.plan_content_sha256 !== revision',
  'false',
  view,
  'missing or invalid revision',
);
add(
  'policy selection scope must match',
  policies,
  'scopeKey(view.scope) !== scopeKey(plan)',
  'false',
  core,
  'policy matching checks',
);
add(
  'policy review must not predate plan',
  policies,
  'view.checked_on < plan.checked_on',
  'view.checked_on > plan.checked_on',
  core,
  'policy matching checks',
);
add(
  'policy link must identify same plan',
  policy,
  'link.plan_id !== value.plan_id',
  'false',
  core,
  'policy source and identity guards each stop evidence',
);
add(
  'policy order is exact',
  policy,
  'JSON.stringify(ids) !==\n      JSON.stringify(normalized.map((p) => p.policy_id))',
  'false',
  core,
  'policy IDs, URLs and fragment IDs',
);
add(
  'policy authority URL prefix checked',
  policy,
  '!path.startsWith(prefix)',
  'false',
  core,
  'policy source and identity guards each stop evidence',
);
add(
  'policy prefix alone is not a document',
  policy,
  'path === prefix',
  'false',
  core,
  'policy source and identity guards each stop evidence',
);
add(
  'non-ready may not contain evidence',
  policy,
  '\n      value.policies.length ||',
  '\n      false ||',
  core,
  'non-ready',
);
add(
  'review cannot predate policy capture',
  policy,
  'checked < s.captured_at.slice(0, 10)',
  'false',
  core,
  'policy source and identity guards each stop evidence',
);
add(
  'exact read delay',
  'src/features/programs/useProgramDemoLoad.ts',
  ': 300,',
  ': 301,',
  demo,
  'the normal read',
);
add(
  'unmount cancels timer',
  'src/features/programs/useProgramDemoLoad.ts',
  'clearTimeout(timer);',
  'void timer;',
  demo,
  'forever schedules nothing',
);
add(
  'scenario and speed remount session',
  'src/pages/ProgramsDemoPage.tsx',
  'key={`${options.scenario}:${options.speed}`}',
  'key="fixed"',
  demo,
  'scenario and speed changes reset',
);
add(
  'generated plan field type guarded',
  'src/api/programs.ts',
  'source_title: string;',
  'source_title: number;',
  null,
  'src/api/programs.types.test.ts',
  'types',
);
add(
  'generated nested policy source guarded',
  'src/api/programs.ts',
  'page_title: string;',
  'page_title: number;',
  null,
  'src/api/programs.types.test.ts',
  'types',
);
// Check every anchor before starting baseline or mutating the isolated copy.
for (const c of cases) {
  const original = readFileSync(join(snapshot, c.file), 'utf8');
  if (original.split(c.from).length !== 2)
    throw Error(c.id + ': expected one mutation anchor');
}
if (
  run([tsc, '--noEmit', '--pretty', 'false'], 'baseline-types').status !== 0 ||
  run([vitest, 'run'], 'baseline-tests', 90000).status !== 0
)
  throw Error('Snapshot baseline failed');
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
