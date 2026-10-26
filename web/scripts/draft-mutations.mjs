// R4b: named mutations of the draft component, its answer check, its small functions, the demo and R4a's draft slot.
// Each runs against an isolated copy of src/ (a junction to node_modules) after a clean baseline of types and tests;
// a mutation counts as killed only when the named test fails on an assertion (or, for a type mutation, the named
// type test fails to compile). The working tree is hashed before and after and must not change.
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
    'draft-mutations-' + new Date().toISOString().replaceAll(/[:.]/g, '-'),
  );
mkdirSync(output, { recursive: true });
const snapshot = mkdtempSync(join(realpathSync.native(tmpdir()), 'neu-draft-'));
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
    id: 'D' + String(cases.length + 1).padStart(2, '0'),
    label,
    file,
    from,
    to,
    test,
    expected,
    mode,
  });
}
const model = 'src/models/planDraft.ts',
  ui = 'src/features/programs/PlanDraft.tsx',
  slot = 'src/features/programs/ProgramCurriculum.tsx',
  demoPage = 'src/pages/PlanDraftDemoPage.tsx',
  demoData = 'src/fixtures/draftDemo.ts',
  types = 'src/api/draft.ts';
const modelTest = 'src/models/planDraft.test.ts',
  view = 'src/features/programs/PlanDraft.test.tsx',
  slotTest = 'src/features/programs/ProgramCurriculum.draft.test.tsx',
  demo = 'src/pages/PlanDraftDemoPage.test.tsx',
  typeTest = 'src/api/draft.types.test.ts';

// The answer check (spec section 4).
add(
  'version must be lowercase hex',
  model,
  '!hash(value.plan_content_sha256)',
  '!string(value.plan_content_sha256)',
  modelTest,
  'plan_content_sha256 uppercase hex',
);
add(
  'at most 20 courses',
  model,
  'listOf(courses, MAX_DRAFT_COURSES, course)',
  'listOf(courses, 21, course)',
  modelTest,
  'a full draft of 20 is fine, 21 is not',
);
add(
  'course codes are unique',
  model,
  'new Set(codes).size !== codes.length',
  'false',
  modelTest,
  'two rows with one code',
);
add(
  'course_id is at most 200 characters',
  model,
  'boundedText(v.course_id, 1, 200)',
  'boundedText(v.course_id, 1, 201)',
  modelTest,
  'a course_id of',
);
add(
  'code digits are ASCII only',
  model,
  'const CODE = /[A-Z]{2,4} [0-9]{4}[A-Z]?/;',
  'const CODE = /[A-Z]{2,4} \\p{Nd}{4}[A-Z]?/u;',
  modelTest,
  'a course code of',
);
add(
  'name length counts code points',
  model,
  'boundedText(v.name, 1, 500)',
  'string(v.name) && v.name.length >= 1 && v.name.length <= 500',
  modelTest,
  'a course name of',
);
add(
  'credits at most 12',
  model,
  'integer(v.credits, 0, 12)',
  'integer(v.credits, 0, 13)',
  modelTest,
  'credits of 13',
);
add(
  'credits true is not a number of credits',
  model,
  '(v.credits === null || integer(v.credits, 0, 12))',
  '(v.credits === null || v.credits === true || integer(v.credits, 0, 12))',
  modelTest,
  'credits of true',
);
add(
  'credits key must be there',
  model,
  "Object.hasOwn(v, 'credits') &&\n    (v.credits === null ||",
  'true &&\n    (v.credits == null ||',
  modelTest,
  'credits must be there',
);
add(
  'added names no code twice',
  model,
  'new Set(added).size !== added.length',
  'false',
  modelTest,
  'the same code twice',
);
add(
  'added only names draft courses',
  model,
  '!added.every((code) => codes.includes(code))',
  'false',
  modelTest,
  'a code not in the draft',
);
add(
  'notice kinds are the fourteen',
  model,
  'NOTICE_KINDS.includes(v.kind as DraftNoticeKind)',
  'string(v.kind)',
  modelTest,
  'an unknown kind',
);
add(
  'notice levels are warning or info',
  model,
  "(v.level === 'warning' || v.level === 'info')",
  'string(v.level)',
  modelTest,
  'an unknown level',
);
add(
  'notice text is not empty',
  model,
  "v.text !== ''",
  'true',
  modelTest,
  'empty text',
);
add(
  'at most 10 candidates',
  model,
  '      v.candidates,\n      10,',
  '      v.candidates,\n      11,',
  modelTest,
  '11 candidates',
);
add(
  'a candidate has a name',
  model,
  'object(c) && string(c.code) && string(c.name)',
  'object(c) && string(c.code)',
  modelTest,
  'a candidate without a name',
);
add(
  'candidates_omitted is a count',
  model,
  'count(v.candidates_omitted)',
  'true',
  modelTest,
  'a negative omitted count',
);
add(
  'depth 20 is the deepest',
  model,
  'depth <= MAX_DEPTH &&',
  'depth <= MAX_DEPTH + 1 &&',
  modelTest,
  'depth 20 is the deepest',
);
add(
  'node kind at most 32 characters',
  model,
  'boundedText(v.kind, 1, 32)',
  'boundedText(v.kind, 1, 33)',
  modelTest,
  'node kind of',
);
add(
  'node label is not empty',
  model,
  'boundedText(v.label, 1, 1000)',
  'boundedText(v.label, 0, 1000)',
  modelTest,
  'node label of',
);
add(
  'node status key must be there',
  model,
  "Object.hasOwn(v, 'status') &&\n    STATUSES.includes(v.status)",
  'STATUSES.includes(v.status ?? null)',
  modelTest,
  'a node without status',
);
add(
  'at most 10 reasons',
  model,
  'stringList(v.reasons, 10)',
  'stringList(v.reasons, 11)',
  modelTest,
  'node reasons of',
);
add(
  'at most 20 counted',
  model,
  'stringList(v.counted, 20)',
  'stringList(v.counted, 21)',
  modelTest,
  'node counted of',
);
add(
  'at most 20 possible',
  model,
  'stringList(v.possible, 20)',
  'stringList(v.possible, 21)',
  modelTest,
  'node possible of',
);
add(
  'at most 10 missing',
  model,
  'stringList(v.missing, 10)',
  'stringList(v.missing, 11)',
  modelTest,
  'node missing of',
);
add(
  'shortfall values are counts',
  model,
  'Object.values(v.shortfall).every(count)',
  'true',
  modelTest,
  'node shortfall of',
);
add(
  'at most 40 children',
  model,
  'listOf(v.children, 40,',
  'listOf(v.children, 41,',
  modelTest,
  '40 children are fine, 41 are not',
);
add(
  'every child is a node',
  model,
  '(child) => node(child, depth + 1)',
  '(child) => object(child)',
  modelTest,
  'a bad child spoils the tree',
);
add(
  'at most 20 unplaced',
  model,
  'stringList(result.unplaced, MAX_DRAFT_COURSES)',
  'stringList(result.unplaced)',
  modelTest,
  '21 unplaced codes',
);
add(
  'the counts are counts',
  model,
  '!count(counts.met) ||',
  '',
  modelTest,
  'a negative count',
);

// The small functions (spec sections 6 to 8).
add(
  'zero credits are not unknown',
  model,
  "credits === null ? '学分未知' : `${credits} 学分`",
  "credits ? `${credits} 学分` : '学分未知'",
  modelTest,
  'small functions',
);
add(
  'unknown credits are not zero',
  model,
  "credits === null ? '学分未知' : `${credits} 学分`",
  '`${credits ?? 0} 学分`',
  view,
  'standard-mixed matches',
);
add(
  'no emoji in the tree',
  model,
  "['met', '按你填的满足'],",
  "['met', '✅ 按你填的满足'],",
  modelTest,
  'tree vector',
);
add(
  'operator words',
  model,
  "['any_of', '任选其一（OR）'],",
  "['any_of', '任选其一(OR)'],",
  modelTest,
  'tree vector',
);
add(
  'operator words not from Object.prototype',
  model,
  'OPERATORS.get(node.kind)',
  "({ all_of: '全部分支（AND）', any_of: '任选其一（OR）', select: '组选（非全部必修）' } as Record<string, string>)[node.kind]",
  modelTest,
  'from Object.prototype has no operator word',
);
add(
  'counted leaves out the possible codes',
  model,
  'node.counted.filter((code) => !node.possible.includes(code))',
  'node.counted',
  modelTest,
  'a code both counted and possible',
);
add(
  'the omitted candidates line',
  model,
  'out.push(`${prefix}  另有 ${node.missing_omitted} 项候选／子项未展开。`);',
  'void 0;',
  modelTest,
  'tree vector',
);
add(
  'the omitted reasons line',
  model,
  'out.push(`${prefix}  另有 ${node.reasons_omitted} 项原因未展开。`);',
  'void 0;',
  modelTest,
  'tree vector',
);
add(
  'two spaces a level',
  model,
  "'  '.repeat(depth)",
  "' '.repeat(depth)",
  modelTest,
  'the depth argument indents',
);
add(
  'the status separator',
  model,
  '${STATUS_WORDS.get(node.status)} — ${title}',
  '${STATUS_WORDS.get(node.status)} - ${title}',
  modelTest,
  'tree vector',
);
add(
  'a stale plan gives no retry',
  model,
  '!planGone(failure) && failure.status !== 404',
  'failure.status !== 404',
  modelTest,
  'failure 409 stale',
);
add(
  'unavailable plans may be retried',
  model,
  '!planGone(failure) && failure.status !== 404',
  "failure.reason !== 'unavailable' && !planGone(failure) && failure.status !== 404",
  modelTest,
  'failure 409 unavailable',
);
add(
  'a 422 gives no retry',
  model,
  '&& failure.status !== 422',
  '',
  modelTest,
  'failure 422',
);
add(
  'an unknown 409 reason is a generic failure',
  model,
  "failure.status === 409 && failure.reason === 'unavailable'",
  'failure.status === 409',
  modelTest,
  'failure 409 null',
);
add(
  'the 404 sentence',
  model,
  "'找不到这个培养方案或方案，草案没有计算。'",
  "'找不到这个培养方案，草案没有计算。'",
  modelTest,
  'failure 404',
);

// The component (spec sections 3, 5 and 9).
add(
  'a draft plan shows nothing',
  ui,
  "if (props.plan.review_status !== 'source_checked') return null;",
  '',
  view,
  'a plan not checked against its sources shows nothing',
);
add(
  'the version is compared',
  ui,
  'parsed.answer.plan_content_sha256 === props.planContentSha256',
  'true',
  view,
  'standard-other-revision matches',
);
add(
  'checking still adds',
  ui,
  'if (!props.checking) props.onAdd(text);',
  'props.onAdd(text);',
  view,
  'while a check is on its way add does nothing',
);
add(
  'add is disabled instead of aria-disabled',
  ui,
  'aria-disabled={props.checking}',
  'disabled={props.checking}',
  view,
  'no button anywhere uses the disabled attribute',
);
add(
  'add trims the text',
  ui,
  'if (!props.checking) props.onAdd(text);',
  'if (!props.checking) props.onAdd(text.trim());',
  view,
  'add sends the typed text exactly as typed',
);
add(
  'add empties the box',
  ui,
  'if (!props.checking) props.onAdd(text);',
  "if (!props.checking) { props.onAdd(text); setText(''); }",
  view,
  'add sends the typed text exactly as typed',
);
add(
  'clear keeps the box',
  ui,
  "setText('');\n            props.onClear();",
  'props.onClear();',
  view,
  'clear empties the box',
);
add(
  'remove leaves focus where it was',
  ui,
  'focusFirst(count);\n            props.onRemove(id);',
  'props.onRemove(id);',
  view,
  'remove first moves focus to the course count',
);
add(
  'remove moves focus only after the callback',
  ui,
  'focusFirst(count);\n            props.onRemove(id);',
  'props.onRemove(id);\n            focusFirst(count);',
  view,
  'remove first moves focus to the course count',
);
add(
  'retry leaves focus where it was',
  ui,
  'focusFirst(heading);\n                props.onRetry();',
  'props.onRetry();',
  view,
  'retry first moves focus to the heading',
);
add(
  'moving focus scrolls',
  ui,
  'target.current?.focus({ preventScroll: true })',
  'target.current?.focus()',
  view,
  'focus',
);
add(
  'the course line becomes a link',
  ui,
  '{`${c.code} · ${c.name} · ${creditsText(c.credits)}`}',
  '<a href={`/course/${c.course_id}`}>{`${c.code} · ${c.name} · ${creditsText(c.credits)}`}</a>',
  view,
  'there is no anchor',
);
add(
  'a complete plan gets the partial note',
  ui,
  "plan.coverage === 'partial' &&",
  'true &&',
  view,
  'align-mixed matches',
);
add(
  'the count is another number',
  ui,
  '已填 ${answer.courses.length}/',
  '已填 ${answer.added.length}/',
  view,
  'standard-mixed matches',
);
add(
  'the summary uses another count',
  ui,
  '${met} 组满足、${missing} 组还缺',
  '${met} 组满足、${unknown} 组还缺',
  view,
  'standard-empty matches',
);
add(
  'unplaced codes joined otherwise',
  ui,
  "answer.result.unplaced.join('、')",
  "answer.result.unplaced.join(', ')",
  view,
  'standard-full matches',
);
add(
  'omitted candidates not said',
  ui,
  'n.candidates_omitted > 0 &&',
  'false &&',
  view,
  'standard-notices matches',
);
add(
  'notice level ignored',
  ui,
  '<p data-kind="notice" data-level={n.level}>',
  '<p data-kind="notice" data-level="warning">',
  view,
  'standard-all-present matches',
);
add(
  'retry offered for every failure',
  ui,
  'canRetryDraft(props.failure) &&',
  'true &&',
  view,
  'standard-404 matches',
);
add(
  'tree lines not on lines of their own',
  ui,
  "{i > 0 && '\\n'}",
  "{i > 0 && ' '}",
  view,
  'the rule tree is one block of lines',
);
add(
  'the failure shows the API reason',
  ui,
  '{draftFailureMessage(props.failure)}',
  '{draftFailureMessage(props.failure) + (props.failure.reason ?? props.failure.errorType ?? "")}',
  view,
  'standard-409-unavailable matches',
);
add(
  'no checking line',
  ui,
  '{props.checking && <span data-kind="status">',
  '{false && <span data-kind="status">',
  view,
  'standard-checking-first matches',
);
add(
  'the answer goes away during a failure',
  ui,
  '      {answer && (\n        <Result',
  '      {answer && !props.failure && (\n        <Result',
  view,
  'standard-409-unavailable matches',
);
add(
  'the answer goes away during a check',
  ui,
  '      {answer && (\n        <Result',
  '      {answer && !props.checking && (\n        <Result',
  view,
  'standard-checking-again matches',
);
add(
  'the status region comes and goes',
  ui,
  '<div role="status" className={styles.live}>',
  "<div role={props.checking ? 'status' : undefined} className={styles.live}>",
  view,
  'the checking line is in a status region',
);
add(
  'the box takes more than 4000 characters',
  ui,
  'maxLength={DRAFT_INPUT_MAX}',
  'maxLength={DRAFT_INPUT_MAX + 1}',
  view,
  'standard-empty matches',
);

// R4a's draft slot (spec section 1 step 3).
add(
  'the draft shows without a plan',
  slot,
  '{plan && props.draft}',
  '{props.draft}',
  slotTest,
  'nothing of the draft shows when',
);
add(
  'the draft inside the plan block',
  slot,
  '        </section>\n      )}\n      {plan && props.draft}',
  '          {props.draft}\n        </section>\n      )}',
  slotTest,
  'choosing another plan keeps the same draft element',
);

// The demo (spec section 12).
add(
  'the default scene',
  demoData,
  ": 'standard-mixed';",
  ": 'standard-add';",
  demo,
  'only known scenes and speeds are taken',
);
add(
  'scene names from Object.prototype',
  demoData,
  'Object.hasOwn(draftScenarios, candidate)',
  'candidate in draftScenarios',
  demo,
  'only known scenes and speeds are taken',
);
add(
  'slow is four times normal',
  demoData,
  '? 1200',
  '? 900',
  demo,
  'at slow speed',
);
add(
  'forever comes back',
  demoData,
  "speed === 'forever'\n    ? null",
  "speed === 'forever'\n    ? 30000",
  demo,
  'forever never brings the scene',
);
add(
  'the first check is not shown',
  demoPage,
  'const [arrived, setArrived] = useState(false);',
  'const [arrived, setArrived] = useState(true);',
  demo,
  'at normal speed',
);
add(
  'a callback changes the answer',
  demoPage,
  'onRemove={(id) => setNotice(`演示：移除 ${id}`)}',
  'onRemove={() => setArrived(false)}',
  demo,
  'each button writes its sentence',
);
add(
  'the view sentence',
  demoPage,
  '`演示：这里会打开 ${id}`',
  '`演示：打开 ${id}`',
  demo,
  'each button writes its sentence',
);
add(
  'a control change keeps the session',
  demoPage,
  'key={`${options.scenario}:${options.speed}`}',
  'key="session"',
  demo,
  'a new scene or speed shows the first check again',
);

// The hand-written types against the generated ones.
add(
  'notice level type',
  types,
  "level: 'warning' | 'info';",
  "level: 'warning';",
  null,
  typeTest,
  'types',
);
add(
  'credits type',
  types,
  'credits: number | null;',
  'credits: string | null;',
  null,
  typeTest,
  'types',
);
add(
  'missing_omitted type',
  types,
  'missing_omitted: number;',
  'missing_omitted: string;',
  null,
  typeTest,
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
  run([vitest, 'run'], 'baseline-tests', 120000).status !== 0
)
  throw Error('Snapshot baseline failed');
const results = [];
for (const c of cases) {
  const file = join(snapshot, c.file),
    original = readFileSync(file, 'utf8');
  if (original.split(c.from).length !== 2)
    throw Error(c.id + ': expected one mutation anchor');
  const changed = original.replace(c.from, () => c.to),
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
console.info(
  `${results.filter((r) => r.killed).length}/${results.length} killed; source unchanged: ${sourceUnchanged}`,
);
if (!sourceUnchanged || results.some((r) => !r.killed)) process.exitCode = 1;
