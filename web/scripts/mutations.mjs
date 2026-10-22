import { createHash } from 'node:crypto';
import {
  cpSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
  readdirSync,
  symlinkSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

const root = process.cwd();
if (
  JSON.parse(readFileSync(join(root, 'package.json'), 'utf8')).name !==
  'neu-compass-web'
)
  throw new Error('Run from web/');
const runId = new Date().toISOString().replaceAll(/[:.]/g, '-');
const output = join(root, 'artifacts', `mutations-${runId}`);
mkdirSync(output, { recursive: true });
// Windows TEMP can use an 8.3 alias; Vite needs canonical paths for module IDs.
const taskTemp = mkdtempSync(
  join(realpathSync.native(tmpdir()), 'neu-compass-r1-'),
);
console.info(`Evidence: ${output}`);
const configFiles = [
  'package.json',
  'package-lock.json',
  'tsconfig.json',
  'vite.config.ts',
  'eslint.config.js',
];
function sourcePaths(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) =>
    entry.isDirectory()
      ? sourcePaths(join(directory, entry.name))
      : [join(directory, entry.name)],
  );
}
function freeze() {
  return Object.fromEntries(
    [
      ...sourcePaths(join(root, 'src')),
      ...sourcePaths(join(root, 'scripts')),
      ...configFiles.map((file) => join(root, file)),
    ].map((file) => [
      file,
      createHash('sha256').update(readFileSync(file)).digest('hex'),
    ]),
  );
}
const frozen = freeze();
function snapshot(name) {
  const path = join(taskTemp, name);
  mkdirSync(path);
  cpSync(join(root, 'src'), join(path, 'src'), { recursive: true });
  for (const file of configFiles) cpSync(join(root, file), join(path, file));
  symlinkSync(
    resolve(root, 'node_modules'),
    join(path, 'node_modules'),
    process.platform === 'win32' ? 'junction' : 'dir',
  );
  return path;
}
function run(cwd, args, name) {
  const result = spawnSync(process.execPath, args, {
    cwd,
    encoding: 'utf8',
    timeout: 45000,
    maxBuffer: 8 * 1024 * 1024,
    windowsHide: true,
  });
  writeFileSync(
    join(output, `${name}.log`),
    (result.stdout ?? '') +
      (result.stderr ?? '') +
      (result.error?.message ?? ''),
    { flag: 'wx' },
  );
  return result;
}
const vitest = join(root, 'node_modules/vitest/vitest.mjs');
const tsc = join(root, 'node_modules/typescript/bin/tsc');
const baseline = snapshot('baseline');
const baseTests = run(baseline, [vitest, 'run'], 'baseline-tests');
const baseTypes = run(baseline, [tsc, '--noEmit'], 'baseline-types');
if (baseTests.status !== 0 || baseTypes.status !== 0)
  throw new Error('Unmutated snapshot must pass first');
const cases = [
  [
    'M01',
    'button variant',
    'src/components/Button.tsx',
    'styles[variant]',
    'styles.ghost',
    'src/components/primitives.test.tsx',
    'uses primary variant',
  ],
  [
    'M02',
    'disabled button',
    'src/components/Button.tsx',
    '{...props}',
    '{...props} disabled={false}',
    'src/components/primitives.test.tsx',
    'does not fire when disabled',
  ],
  [
    'M03',
    'required icon label',
    'src/components/IconButton.tsx',
    "'aria-label': string;",
    "'aria-label'?: string;",
    'types',
    'icon-button-types.tsx',
  ],
  [
    'M04',
    'literal course code',
    'src/components/CourseCode.tsx',
    '{children}',
    "{'CS 5800'}",
    'src/components/primitives.test.tsx',
    'renders literal text',
  ],
  [
    'M05',
    'eight topic cap',
    'src/components/Chips.tsx',
    'slice(0, 8)',
    'slice(0, 9)',
    'src/components/primitives.test.tsx',
    'caps nine topics',
  ],
  [
    'M06',
    'collapsed data note',
    'src/components/DataNote.tsx',
    '<details className={styles.note}>',
    '<details open className={styles.note}>',
    'src/components/primitives.test.tsx',
    'initially collapsed',
  ],
  [
    'M07',
    'switch state',
    'src/components/Toggle.tsx',
    'onChange(!checked)',
    'onChange(checked)',
    'src/components/controls.test.tsx',
    'Toggle reports and changes',
  ],
  [
    'M08',
    'all and any groups',
    'src/components/RequisiteTree.tsx',
    "node.kind === 'any' ? '满足其一' : '都要'",
    "node.kind === 'any' ? '都要' : '都要'",
    'src/components/controls.test.tsx',
    'keeps nested all/any',
  ],
  [
    'M09',
    'exact requisite leaf',
    'src/components/RequisiteTree.tsx',
    'onOpen(node.code)',
    "onOpen('CS 5800')",
    'src/components/controls.test.tsx',
    'each leaf opens the exact',
  ],
  [
    'M10',
    'keyboard select',
    'src/components/Select.tsx',
    'onValueChange={onChange}',
    'onValueChange={() => {}}',
    'src/components/controls.test.tsx',
    'opens, selects and closes',
  ],
  [
    'M11',
    'Enter versus Shift Enter',
    'src/layout/AskBar.tsx',
    '!event.shiftKey',
    'event.shiftKey',
    'src/layout/AskBar.test.tsx',
    'Enter sends trimmed',
  ],
  [
    'M12',
    'save consent defaults off',
    'src/layout/AskBar.tsx',
    'useState(false)',
    'useState(true)',
    'src/layout/AskBar.test.tsx',
    'leaves consent off',
  ],
  [
    'M13',
    'current navigation',
    'src/layout/Sidebar.tsx',
    "aria-current={active ? 'page' : undefined}",
    'aria-current={undefined}',
    'src/layout/navigation.test.tsx',
    'marks only the current destination',
  ],
  [
    'M14',
    'mobile open and close',
    'src/layout/MobileNav.tsx',
    'onOpenChange={setOpen}',
    'onOpenChange={() => {}}',
    'src/layout/navigation.test.tsx',
    'mobile trigger reports expansion',
  ],
  [
    'M15',
    'shared comparison rows',
    'src/pages/ComparePage.tsx',
    '!onlyDifferent ||',
    'false ||',
    'src/pages/pages.test.tsx',
    'compare switch restores shared rows',
  ],
  [
    'M16',
    'comparison removal',
    'src/layout/PrototypeContext.tsx',
    'previous.filter((item) => item !== code)',
    'previous.filter((item) => item === code)',
    'src/pages/pages.test.tsx',
    'removal keeps other columns',
  ],
  [
    'M17',
    'focus without scroll jump',
    'src/layout/AppShell.tsx',
    '.focus({ preventScroll: true })',
    '.focus()',
    'src/pages/pages.test.tsx',
    'route focus does not scroll',
  ],
];
const results = [];
cases.push(
  [
    'M18',
    'per-question consent reset',
    'src/layout/AskBar.tsx',
    'setAllowSave(false);',
    '',
    'src/layout/AskBar.test.tsx',
    'resets consent after sending',
  ],
  [
    'M19',
    'comparison plan project consistency',
    'src/layout/PrototypeContext.tsx',
    "if (value !== 'none') setProjectValue('cs-ms');",
    "if (value !== 'none') setProjectValue('none');",
    'src/pages/pages.test.tsx',
    'choosing a comparison plan keeps its fixture project consistent',
  ],
  [
    'M20',
    'neighbor focus after removal',
    'src/pages/ComparePage.tsx',
    'selected[index + 1] ?? selected[index - 1]',
    'selected[index - 1] ?? selected[index + 1]',
    'src/pages/pages.test.tsx',
    'removing CS 6140 moves keyboard focus to the neighboring DS 5220',
  ],
  [
    'M21',
    'last course empty action focus',
    'src/pages/ComparePage.tsx',
    "if (target === 'empty') emptyAction.current?.focus();",
    "if (target === 'empty') { /* broken empty-state focus */ }",
    'src/pages/pages.test.tsx',
    'removing the last comparison course focuses the empty-state action',
  ],
  [
    'M22',
    'clear comparison focus request',
    'src/pages/ComparePage.tsx',
    "pendingFocus.current = 'empty';",
    'pendingFocus.current = null;',
    'src/pages/pages.test.tsx',
    'clearing comparison focuses its remaining keyboard action',
  ],
  [
    'M23',
    'example answer focus',
    'src/pages/SearchPage.tsx',
    'answer.current?.focus({ preventScroll: true });',
    'answer.current?.blur();',
    'src/pages/pages.test.tsx',
    'choosing the empty-page example CS 5800 讲什么？ focuses the new answer',
  ],
  [
    'M24',
    'button DOM ref forwarding',
    'src/components/Button.tsx',
    '{...props}',
    '{...props} ref={undefined}',
    'src/components/primitives.test.tsx',
    'forwards its DOM ref for keyboard focus recovery',
  ],
  [
    'M25',
    'unrelated update steals focus',
    'src/pages/ComparePage.tsx',
    'onChange={setOnlyDifferent}',
    'onChange={(value) => { setOnlyDifferent(value); removeButtons.current.values().next().value?.focus(); }}',
    'src/pages/pages.test.tsx',
    'comparison focus is not stolen by an unrelated row-filter update',
  ],
  [
    'M26',
    'static route case agreement',
    'src/layout/routePresentation.ts',
    'matchPath(path, pathname)',
    'matchPath({ path, caseSensitive: true }, pathname)',
    'src/pages/pages.test.tsx',
    'route chrome agrees with the rendered page at /COMPARE',
  ],
  [
    'M27',
    'static route must match to the end',
    'src/layout/routePresentation.ts',
    'matchPath(path, pathname)',
    'matchPath({ path, end: false }, pathname)',
    'src/pages/pages.test.tsx',
    'invalid path /compare/details stays a genuine 404',
  ],
  [
    'M28',
    'course route is not a prefix test',
    'src/layout/routePresentation.ts',
    "matchPath('/course/:code', pathname)",
    "pathname.startsWith('/course/')",
    'src/pages/pages.test.tsx',
    'invalid path /course/CS-6140/extra stays a genuine 404',
  ],
  [
    'M29',
    'navigation follows the matched route',
    'src/layout/Sidebar.tsx',
    'const active = path === navigationPath;',
    'const active = path === pathname;',
    'src/pages/pages.test.tsx',
    'route chrome agrees with the rendered page at /compare/',
  ],
  [
    'M30',
    'Co-op filters intersect',
    'src/models/coop.ts',
    'return matchesIndustry && matchesQuery;',
    'return matchesIndustry || matchesQuery;',
    'src/pages/CoopPage.spec.test.tsx',
    'industry and keyword filters intersect',
  ],
  [
    'M31',
    'Co-op keyword normalization',
    'src/models/coop.ts',
    'query.trim().toLowerCase()',
    'query',
    'src/pages/CoopPage.spec.test.tsx',
    'keyword search is trimmed and case-insensitive',
  ],
  [
    'M32',
    'salary tier cannot guarantee interviews',
    'src/components/CoopCard.tsx',
    'record.visibility_level === 1 && !hasInterview',
    'record.visibility_level >= 1 && !hasInterview',
    'src/pages/CoopPage.spec.test.tsx',
    'salary-tier records do not invent interview availability',
  ],
  [
    'M33',
    'guest packet remains redacted',
    'src/fixtures/coopDemo.ts',
    'records: guest.body as CoopRecord[]',
    'records: member2.body as CoopRecord[]',
    'src/pages/CoopDemoPage.test.tsx',
    'unknown demo input safely falls back',
  ],
  [
    'M34',
    'list failure is not empty',
    'src/pages/CoopPage.tsx',
    '<p role="alert">Co-op 列表暂时加载不了，请稍后重试。</p>',
    '<p role="alert">Co-op 列表暂时加载不了，请稍后重试。</p><p>还没有记录</p>',
    'src/pages/CoopPage.spec.test.tsx',
    'error is separate from empty',
  ],
  [
    'M35',
    'injected viewer scope resets list',
    'src/pages/CoopPage.tsx',
    'key={scope}',
    'key="static-scope"',
    'src/pages/CoopPage.spec.test.tsx',
    'injected viewer scope resets',
  ],
  [
    'M36',
    'unknown viewer fails closed',
    'src/fixtures/coopDemo.ts',
    ": 'guest';",
    ": 'member2';",
    'src/pages/CoopDemoPage.test.tsx',
    'unknown demo input safely falls back',
  ],
  [
    'M37',
    'clear resets industry',
    'src/pages/CoopPage.tsx',
    "setIndustry('all');",
    "setIndustry('other');",
    'src/pages/CoopPage.spec.test.tsx',
    'industry and keyword filters intersect',
  ],
  [
    'M38',
    'returned interview is displayed',
    'src/components/CoopCard.tsx',
    'record.interview_summary && (',
    'false && (',
    'src/pages/CoopPage.spec.test.tsx',
    'returned interview fields use collapsed native details',
  ],
  [
    'M39',
    'student text is not HTML',
    'src/components/CoopCard.tsx',
    '<p>{record.interview_summary}</p>',
    '<p dangerouslySetInnerHTML={{ __html: record.interview_summary }} />',
    'src/components/CoopCard.test.tsx',
    'student-controlled fields remain literal text',
  ],
  [
    'M40',
    'clear restores focus',
    'src/pages/CoopPage.tsx',
    'search.current?.focus();',
    'search.current?.blur();',
    'src/pages/CoopPage.spec.test.tsx',
    'industry and keyword filters intersect',
  ],
  [
    'M41',
    'trim required fields',
    'src/models/coop.ts',
    'if (!draft[name].trim())',
    'if (!draft[name])',
    'src/pages/CoopPage.spec.test.tsx',
    'whitespace-only',
  ],
  [
    'M42',
    'duration upper bound',
    'src/models/coop.ts',
    'duration > 8',
    'duration > 9',
    'src/pages/CoopPage.spec.test.tsx',
    'invalid duration 9',
  ],
  [
    'M43',
    'integer duration',
    'src/models/coop.ts',
    '!Number.isInteger(duration)',
    'false',
    'src/pages/CoopPage.spec.test.tsx',
    'invalid duration 2.5',
  ],
  [
    'M44',
    'optional duration remains null',
    'src/models/coop.ts',
    "draft.duration_months.trim() === '' ? null : Number(draft.duration_months)",
    "draft.duration_months.trim() === '' ? 6 : Number(draft.duration_months)",
    'src/pages/CoopPage.spec.test.tsx',
    'all optional empty fields become null',
  ],
  [
    'M45',
    'request trims company',
    'src/models/coop.ts',
    'company: draft.company.trim(),',
    'company: draft.company,',
    'src/pages/CoopPage.spec.test.tsx',
    'request has exact trimmed keys',
  ],
  [
    'M46',
    'all course separators',
    'src/models/coop.ts',
    '.split(/[,，、]/)',
    ".split(',')",
    'src/pages/CoopPage.spec.test.tsx',
    'request has exact trimmed keys',
  ],
  [
    'M47',
    'courses deduplicate',
    'src/models/coop.ts',
    '...new Set(',
    '...Array.from(',
    'src/pages/CoopPage.spec.test.tsx',
    'request has exact trimmed keys',
  ],
  [
    'M48',
    'length limit enforced',
    'src/models/coop.ts',
    'length > 10000',
    'length > 10001',
    'src/pages/CoopPage.spec.test.tsx',
    'text over 10000 Unicode',
  ],
  [
    'M49',
    'Unicode character parity',
    'src/models/coop.ts',
    'Array.from(draft[name].trim()).length',
    'draft[name].trim().length',
    'src/pages/CoopPage.spec.test.tsx',
    '10000 astral characters',
  ],
  [
    'M50',
    'in-flight guard',
    'src/components/CoopForm.tsx',
    'if (locked.current) return;',
    'if (false) return;',
    'src/pages/CoopPage.spec.test.tsx',
    'in-flight submission disables',
  ],
  [
    'M51',
    'success clears draft',
    'src/components/CoopForm.tsx',
    'setDraft({ ...emptyDraft });',
    'setDraft(current => current);',
    'src/pages/CoopPage.spec.test.tsx',
    'success clears every field',
  ],
  [
    'M52',
    'result receives focus',
    'src/components/CoopForm.tsx',
    'result.current?.focus();',
    'result.current?.blur();',
    'src/pages/CoopPage.spec.test.tsx',
    'success clears every field',
  ],
  [
    'M53',
    'duplicate prefix',
    'src/components/CoopForm.tsx',
    'outcome.result.duplicate ?',
    'false ?',
    'src/pages/CoopPage.spec.test.tsx',
    'success clears every field and focuses exact outcome for upload-duplicate-pending',
  ],
  [
    'M54',
    '422 field mapping',
    'src/models/coop.ts',
    "const name = detail?.split(':', 1)[0];",
    'const name = undefined;',
    'src/pages/CoopPage.spec.test.tsx',
    '422 safely maps known field',
  ],
  [
    'M55',
    'server detail never displayed',
    'src/components/CoopForm.tsx',
    'failureMessage(outcome.status, outcome.body !== null)',
    'outcome.body?.detail ?? failureMessage(outcome.status, false)',
    'src/pages/CoopPage.spec.test.tsx',
    'failure 422 preserves fields',
  ],
  [
    'M56',
    '401 login action',
    'src/components/CoopForm.tsx',
    '{notice.login &&',
    '{false &&',
    'src/pages/CoopPage.spec.test.tsx',
    'failure 401 preserves fields',
  ],
  [
    'M57',
    'viewer count is props only',
    'src/pages/CoopPage.tsx',
    '{viewer.contributionCount} 条',
    '{viewer.contributionCount + 1} 条',
    'src/pages/CoopPage.spec.test.tsx',
    'success clears every field',
  ],
  [
    'M58',
    'demo delay is 400ms',
    'src/pages/CoopDemoPage.tsx',
    'window.setTimeout(resolve, 400)',
    'window.setTimeout(resolve, 0)',
    'src/pages/CoopDemoPage.test.tsx',
    'demo submission waits 400ms',
  ],
  [
    'M59',
    'salary tier lock',
    'src/components/CoopCard.tsx',
    'record.visibility_level === 2 ?',
    'record.visibility_level === 1 ?',
    'src/pages/CoopPage.spec.test.tsx',
    'API fixture visibility and exact lock placement',
  ],
  [
    'M60',
    'retry callback called',
    'src/pages/CoopPage.tsx',
    'onClick={() => onRetryList()}',
    'onClick={() => undefined}',
    'src/pages/CoopPage.spec.test.tsx',
    'error is separate from empty',
  ],
);
for (const [id, label, file, from, to, test, expected] of cases) {
  const path = snapshot(id);
  const target = join(path, file);
  const source = readFileSync(target, 'utf8');
  if (source.split(from).length !== 2)
    throw new Error(`${id}: expected one mutation anchor`);
  writeFileSync(target, source.replace(from, to));
  const report = join(output, `${id}.json`);
  const result = run(
    path,
    test === 'types'
      ? [tsc, '--noEmit']
      : [
          vitest,
          'run',
          test,
          '-t',
          expected.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'),
          '--reporter=json',
          '--outputFile',
          report,
        ],
    id,
  );
  let failures = [];
  if (test !== 'types' && existsSync(report)) {
    const data = JSON.parse(readFileSync(report, 'utf8'));
    failures = data.testResults.flatMap((suite) =>
      suite.assertionResults
        .filter((item) => item.status === 'failed')
        .map((item) => item.fullName),
    );
  }
  const typeDiagnostics = (result.stdout ?? '')
    .split('\n')
    .filter((line) => line.includes(': error TS'));
  const namedTypeFailure =
    result.status === 2 &&
    typeDiagnostics.length === 1 &&
    typeDiagnostics[0].includes(expected) &&
    typeDiagnostics[0].includes('TS2578');
  const killed =
    !result.error &&
    (test === 'types'
      ? namedTypeFailure
      : result.status === 1 &&
        failures.some((name) => name.includes(expected)));
  results.push({
    id,
    label,
    killed,
    exitCode: result.status,
    failures,
    expected,
    snapshot: path,
  });
  console.info(`${id} ${killed ? 'KILLED' : 'UNRESOLVED'}: ${label}`);
}
const unchanged = JSON.stringify(frozen) === JSON.stringify(freeze());
writeFileSync(
  join(output, 'summary.json'),
  JSON.stringify(
    {
      baseline: 'passed',
      frozen,
      sourceUnchanged: unchanged,
      snapshots: taskTemp,
      results,
    },
    null,
    2,
  ),
  { flag: 'wx' },
);
console.info(`Evidence: ${output}`);
if (!unchanged || results.some((result) => !result.killed))
  process.exitCode = 1;
