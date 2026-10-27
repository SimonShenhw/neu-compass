// R4b: named mutations of the draft component, its answer check, its small functions, the demo and R4a's draft slot.
// Each runs against an isolated copy of src/ (a junction to node_modules) after a clean baseline of types and tests;
// a mutation counts as killed only when Vitest fails and one of the failed tests is the named one, whatever failed
// it (an assertion, a missing element or a thrown error); a type mutation, only when the named type test fails to
// compile on that field. The working tree is hashed before and after and must not change; the copy is removed when
// the process exits, after the run or an error, its junctions first. A run stopped from outside (Ctrl+C, a killed
// process, a restart) leaves it in the temp folder.
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
    'draft-mutations-' + new Date().toISOString().replaceAll(/[:.]/g, '-'),
  );
mkdirSync(output, { recursive: true });
const snapshot = mkdtempSync(join(realpathSync.native(tmpdir()), 'neu-draft-'));
// The copy goes when the process exits, a failed baseline or a bad anchor included. Its junctions go first, so removing
// it cannot reach the node_modules behind them; if one cannot be removed, the copy stays. There is no signal handler:
// the run is synchronous, so one would only run after the last mutant, and Ctrl+C would no longer stop the run.
process.on('exit', () => {
  const links = ['node_modules', 'tools/openapi-types/node_modules'].map((l) =>
    join(snapshot, l),
  );
  for (const link of links)
    if (lstatSync(link, { throwIfNoEntry: false })?.isSymbolicLink())
      unlinkSync(link);
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
const cases = [];
// A mutation is one edit, or several edits to the same file made in order (`from` and `to` as lists); each anchor
// must occur exactly once when its edit is made.
function mutate(text, c) {
  const froms = [c.from].flat(),
    tos = [c.to].flat();
  froms.forEach((from, i) => {
    if (text.split(from).length !== 2)
      throw Error(c.id + ': expected one mutation anchor');
    text = text.replace(from, () => tos[i]);
  });
  return text;
}
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
  css = 'src/features/programs/PlanDraft.module.css',
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
  'aria-disabled={props.checking}\n          className={styles.add}',
  'disabled={props.checking}\n          className={styles.add}',
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
  '<div key={i} className={styles.notice} data-level={n.level}>',
  '<div key={i} className={styles.notice} data-level="warning">',
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

// Review round 31: each fix undone, and the gaps the reviewers' own mutants found (B31's IDs in the labels).
add(
  'a failure like the last keeps its sentence',
  ui,
  '<Alert key={failureRound} kind="failure">',
  '<Alert kind="failure">',
  view,
  'a retry that fails the same way again draws its sentence afresh',
);
add(
  'a failure like the last rebuilds the retry button',
  ui,
  '<div className={styles.failure}>',
  '<div key={failureRound} className={styles.failure}>',
  view,
  'a retry that fails the same way again draws its sentence afresh',
);
add(
  'rounds never move',
  ui,
  'if (last.value === value) return last.round;',
  'return last.round;',
  view,
  'a retry that fails the same way again draws its sentence afresh',
);
add(
  'an answer like the last keeps its notices',
  ui,
  '<Notices key={answerRound} answer={answer} />',
  '<Notices answer={answer} />',
  view,
  'an answer like the last one draws its notices',
);
add(
  'an answer like the last keeps the count’s words',
  ui,
  '<span key={answerRound}>',
  '<span>',
  view,
  'an answer like the last one draws its notices',
);
add(
  'each answer rebuilds the count line',
  ui,
  '<p ref={countRef} tabIndex={-1} data-kind="count">',
  '<p key={"count" + answerRound} ref={countRef} tabIndex={-1} data-kind="count">',
  view,
  'an answer like the last one draws its notices',
);
add(
  'another malformed answer keeps its warning',
  ui,
  '<Alert key={answerRound} kind="warning">\n          草案结果的格式不对',
  '<Alert kind="warning">\n          草案结果的格式不对',
  view,
  'another answer that cannot be shown draws its warning afresh',
);
add(
  'another answer of another version keeps its warning',
  ui,
  '<Alert key={answerRound} kind="warning">\n          草案结果与当前',
  '<Alert kind="warning">\n          草案结果与当前',
  view,
  'another answer that cannot be shown draws its warning afresh',
);
add(
  'every render redraws the notices',
  ui,
  '<Notices key={answerRound} answer={answer} />',
  '<Notices key={Math.random()} answer={answer} />',
  view,
  'drawing again with the same answer and failure redraws nothing',
);
add(
  'every render redraws the failure',
  ui,
  '<Alert key={failureRound} kind="failure">',
  '<Alert key={Math.random()} kind="failure">',
  view,
  'drawing again with the same answer and failure redraws nothing',
);
add(
  'retry calls back while checking',
  ui,
  'if (props.checking) return;',
  '',
  view,
  'while a check is on its way retry does nothing',
);
add(
  'retry is not aria-disabled while checking',
  ui,
  'aria-disabled={props.checking}\n              className={styles.retry}',
  'className={styles.retry}',
  view,
  'while a check is on its way retry does nothing',
);
add(
  'retry is disabled instead of aria-disabled',
  ui,
  'aria-disabled={props.checking}\n              className={styles.retry}',
  'disabled={props.checking}\n              className={styles.retry}',
  view,
  'no button anywhere uses the disabled attribute',
);
add(
  'B42: the failure hides while a check is on its way',
  ui,
  '{props.failure && (',
  '{props.failure && !props.checking && (',
  view,
  'while a check is on its way retry does nothing',
);
add(
  'the count line takes focus away with it',
  ui,
  'heading.current?.focus({ preventScroll: true });',
  'void 0;',
  view,
  'when the course count goes while it has focus',
);
add(
  'the count line takes focus from elsewhere',
  ui,
  'if (el?.contains(document.activeElement))',
  'if (el !== null)',
  view,
  'when the course count goes while nothing has focus',
);
add(
  'the fallback focus scrolls',
  ui,
  'heading.current?.focus({ preventScroll: true });',
  'heading.current?.focus();',
  view,
  'when the course count goes while it has focus',
);
add(
  'the typed text outlives a plan not checked',
  ui,
  [
    "  if (props.plan.review_status !== 'source_checked') return null;\n  return <Draft {...props} />;",
    "function Draft(props: PlanDraftProps) {\n  const [text, setText] = useState('');",
  ],
  [
    "  const [text, setText] = useState('');\n  if (props.plan.review_status !== 'source_checked') return null;\n  return <Draft {...props} text={text} setText={setText} />;",
    'function Draft(\n  props: PlanDraftProps & { text: string; setText: (text: string) => void },\n) {\n  const { text, setText } = props;',
  ],
  view,
  'goes with a plan not checked against its sources',
);
add(
  'B64b: the typed text goes with every plan change',
  ui,
  "  const [text, setText] = useState('');\n",
  "  const [text, setText] = useState('');\n  const [seenPlan, setSeenPlan] = useState(props.plan.plan_id);\n  if (seenPlan !== props.plan.plan_id) {\n    setSeenPlan(props.plan.plan_id);\n    setText('');\n  }\n",
  view,
  'stays through a check',
);
add(
  'B63b: the typed text goes with each answer',
  ui,
  "  const [text, setText] = useState('');\n",
  "  const [text, setText] = useState('');\n  const [seenAnswer, setSeenAnswer] = useState(props.answer);\n  if (seenAnswer !== props.answer) {\n    setSeenAnswer(props.answer);\n    setText('');\n  }\n",
  view,
  'stays through a check',
);
add(
  'B65b: the last answer that fitted stays on screen',
  ui,
  [
    '  const count = useRef<HTMLParagraphElement | null>(null);\n',
    '      : null;\n  return (',
    '      {answer && (\n        <Result\n          answer={answer}',
  ],
  [
    '  const count = useRef<HTMLParagraphElement | null>(null);\n  const [lastGood, setLastGood] = useState<DraftAnswer | null>(null);\n',
    '      : null;\n  if (answer && answer !== lastGood) setLastGood(answer);\n  const shown = answer ?? lastGood;\n  return (',
    '      {shown && (\n        <Result\n          answer={shown}',
  ],
  view,
  'an answer shown before shows nothing of it once it no longer fits',
);
add(
  'B20: warning notices get the plain box',
  ui,
  '<div key={i} className={styles.notice} data-level={n.level}>',
  '<div key={i} className={styles.notice} data-level="info">',
  view,
  'a notice looks like its level',
);
add(
  'B21: the two notice icons swapped',
  ui,
  '        <TriangleAlert aria-hidden="true" />\n      ) : (\n        <Info aria-hidden="true" />',
  '        <Info aria-hidden="true" />\n      ) : (\n        <TriangleAlert aria-hidden="true" />',
  view,
  'a notice looks like its level',
);
add(
  'the level on the sentence, not on the box',
  ui,
  [
    '<div key={i} className={styles.notice} data-level={n.level}>',
    '<p data-kind="notice">{n.text}</p>',
  ],
  [
    '<div key={i} className={styles.notice}>',
    '<p data-kind="notice" data-level={n.level}>\n          {n.text}\n        </p>',
  ],
  view,
  'a notice looks like its level',
);
add(
  'B22: the rule tree is hidden',
  ui,
  '<pre data-kind="tree" className={styles.tree}>',
  '<pre data-kind="tree" hidden className={styles.tree}>',
  view,
  'standard-mixed hides none of the items',
);
add(
  'the summary is hidden from screen readers',
  ui,
  '<p data-kind="summary">',
  '<p data-kind="summary" aria-hidden="true">',
  view,
  'standard-mixed hides none of the items',
);
add(
  'B24: the version warning is not an alert',
  ui,
  '        <Alert key={answerRound} kind="warning">\n          草案结果与当前所选方案的内容版本不一致；请刷新方案后重试，未显示旧结果。\n        </Alert>',
  '        <p data-kind="warning" className={styles.alert}>\n          草案结果与当前所选方案的内容版本不一致；请刷新方案后重试，未显示旧结果。\n        </p>',
  view,
  'the version warning is an alert too',
);
add(
  'B30: the box gets a placeholder',
  ui,
  '          rows={3}\n',
  '          rows={3}\n          placeholder="例如 CS 5010"\n',
  view,
  'standard-empty shows no text outside',
);
add(
  'a second label with words of its own',
  ui,
  '        学分按核对时的课程记录，不确认具体班次或个人学位计入。\n      </p>\n',
  '        学分按核对时的课程记录，不确认具体班次或个人学位计入。\n      </p>\n      <label>草案不会自动保存。</label>\n',
  view,
  'standard-empty shows no text outside',
);
add(
  'B58: every 409 gets a retry in the component',
  ui,
  '{canRetryDraft(props.failure) && (',
  '{(canRetryDraft(props.failure) || props.failure.status === 409) && (',
  view,
  'the real draft-409-stale failure',
);
add(
  'B59: a plan-gone 409 shows no failure',
  ui,
  '{props.failure && (',
  "{props.failure && !(props.failure.status === 409 && props.failure.reason !== 'unavailable') && (",
  view,
  'the real draft-409-missing failure',
);
add(
  'B70: typing writes to sessionStorage',
  ui,
  'onChange={(e) => setText(e.target.value)}',
  "onChange={(e) => {\n            setText(e.target.value);\n            sessionStorage.setItem('neu-draft-text', e.target.value);\n          }}",
  view,
  'typing and every button keep nothing',
);
add(
  'B71: remove writes the address',
  ui,
  'focusFirst(count);\n            props.onRemove(id);',
  "focusFirst(count);\n            window.history.replaceState(null, '', '?removed=' + id);\n            props.onRemove(id);",
  view,
  'typing and every button keep nothing',
);
add(
  'the answer check logs',
  model,
  'export function parseDraftAnswer(',
  'console.info(0);\nexport function parseDraftAnswer(',
  view,
  'the draft modules keep nothing',
);
add(
  'B27: long words no longer wrap',
  css,
  '  min-width: 0;\n  overflow-wrap: anywhere;\n}\n.draft h3 {',
  '  min-width: 0;\n}\n.draft h3 {',
  view,
  'the stylesheet shows line breaks',
);
add(
  'B28: a course line no longer keeps its line breaks',
  css,
  '.courseText {\n  white-space: pre-wrap;\n}',
  '.courseText {\n}',
  view,
  'the stylesheet shows line breaks',
);
add(
  'warning notices lose their border',
  css,
  ".notice[data-level='warning'] {\n  border-color: var(--accent);",
  ".notice[data-level='warning'] {",
  view,
  'the stylesheet gives a warning notice its border',
);
add(
  'B50: changing one control drops the other',
  demoPage,
  'const next = new URLSearchParams(params);',
  'const next = new URLSearchParams();',
  demo,
  'changing one control keeps the other',
);
add(
  'B51: the first check already shows the failure',
  demoPage,
  '{...(arrived ? draftState(spec) : CHECKING)}',
  '{...(arrived ? draftState(spec) : { ...CHECKING, failure: draftState(spec).failure })}',
  demo,
  'a failure scene shows no failure while its first check',
);
add(
  'B52: a speed reads otherwise',
  demoData,
  "['forever', '一直加载'],",
  "['forever', '永远加载'],",
  demo,
  'the speeds read',
);
add(
  'B01: any space between the letters and the digits',
  model,
  'const CODE = /[A-Z]{2,4} [0-9]{4}[A-Z]?/;',
  'const CODE = /[A-Z]{2,4}\\s[0-9]{4}[A-Z]?/;',
  modelTest,
  'a course code of',
);
add(
  'B02: a lowercase last letter',
  model,
  'const CODE = /[A-Z]{2,4} [0-9]{4}[A-Z]?/;',
  'const CODE = /[A-Z]{2,4} [0-9]{4}[A-Za-z]?/;',
  modelTest,
  'a course code of',
);
add(
  'B03: counted items not checked',
  model,
  'stringList(v.counted, 20)',
  'listOf(v.counted, 20, () => true)',
  modelTest,
  'node counted of',
);
add(
  'B04: missing items not checked',
  model,
  'stringList(v.missing, 10)',
  'listOf(v.missing, 10, () => true)',
  modelTest,
  'node missing of',
);
add(
  'B05: notice text of spaces refused',
  model,
  "v.text !== ''",
  "v.text.trim() !== ''",
  modelTest,
  'notice text only has to be non-empty',
);
add(
  'B06: a candidate name of any type',
  model,
  '(c) => object(c) && string(c.code) && string(c.name),',
  '(c) => object(c) && string(c.code) && c.name !== undefined,',
  modelTest,
  'a candidate name that is not a string',
);
add(
  'B07: the result not checked to be an object',
  model,
  '!object(result) ||',
  '',
  modelTest,
  'null in place of the result',
);
add(
  'B09: the unavailable sentence for any status',
  model,
  "if (failure.status === 409 && failure.reason === 'unavailable')",
  "if (failure.reason === 'unavailable')",
  modelTest,
  'the unavailable sentence is for a 409 only',
);

add(
  'a course takes focus away with it',
  ui,
  '<li key={c.code} ref={keepFocus} className={styles.course}>',
  '<li key={c.code} className={styles.course}>',
  view,
  'when the buttons of a course or the retry button go',
);
add(
  'only the failure block hands focus on, not the retry button alone',
  ui,
  [
    '<div className={styles.failure}>',
    'ref={keepFocus}\n              data-kind="button"\n              data-action="retry"',
  ],
  [
    '<div ref={keepFocus} className={styles.failure}>',
    'data-kind="button"\n              data-action="retry"',
  ],
  view,
  'when the buttons of a course or the retry button go',
);
add(
  'the course count takes focus away with it',
  ui,
  'keep();\n        count.current = null;',
  'count.current = null;',
  view,
  'when the course count goes while it has focus',
);
// Recheck round 1.
add(
  'the retry button alone takes focus away with it',
  ui,
  'ref={keepFocus}\n              data-kind="button"\n              data-action="retry"',
  'data-kind="button"\n              data-action="retry"',
  view,
  'when the buttons of a course or the retry button go',
);
add(
  'B80b: focus borrowed from another element for a moment',
  ui,
  'if (el?.contains(document.activeElement))',
  'if (document.activeElement !== document.body && document.activeElement !== heading.current)',
  view,
  'when the course count goes while focus is elsewhere',
);
add(
  'B94: a new failure redraws the notices',
  ui,
  '<Notices key={answerRound} answer={answer} />',
  '<Notices key={answerRound + ":" + failureRound} answer={answer} />',
  view,
  'a new failure draws only its sentence afresh',
);
add(
  'a new failure redraws the count’s words',
  ui,
  '<span key={answerRound}>',
  '<span key={answerRound + ":" + failureRound}>',
  view,
  'a new failure draws only its sentence afresh',
);
add(
  'B81: the notice box loses its look',
  ui,
  '<div key={i} className={styles.notice} data-level={n.level}>',
  '<div key={i} data-level={n.level}>',
  view,
  'a notice looks like its level',
);
add(
  'B82: a later rule takes the line breaks back',
  css,
  '.courseActions {',
  '.course p {\n  white-space: normal;\n}\n.courseActions {',
  view,
  'the stylesheet shows line breaks',
);
add(
  'B83: a waiting retry is not greyed out',
  css,
  ".add[aria-disabled='true'],\n.retry[aria-disabled='true'] {",
  ".add[aria-disabled='true'] {",
  view,
  'the stylesheet gives a warning notice its border',
);
// Recheck round 2: an element that loses its class loses the rules the stylesheet tests read.
const classes = 'the elements carry the classes those rules are for';
add(
  'B110: a course line loses its class',
  ui,
  '<p data-kind="course" className={styles.courseText}>',
  '<p data-kind="course">',
  view,
  classes,
);
add(
  'B111: the rule tree loses its class',
  ui,
  '<pre data-kind="tree" className={styles.tree}>',
  '<pre data-kind="tree">',
  view,
  classes,
);
add(
  'B112: the codes the plan does not name lose their class',
  ui,
  '<p data-kind="unplaced" className={styles.text}>',
  '<p data-kind="unplaced">',
  view,
  classes,
);
add(
  'B113: the draft loses its class',
  ui,
  '<section aria-labelledby={headingId} className={styles.draft}>',
  '<section aria-labelledby={headingId}>',
  view,
  classes,
);
add(
  'B114: the retry button loses its class',
  ui,
  'className={styles.retry}',
  '',
  view,
  classes,
);
add(
  'a note loses its class',
  ui,
  '<p data-kind="note" className={styles.note}>\n        学分按核对时的课程记录',
  '<p data-kind="note">\n        学分按核对时的课程记录',
  view,
  classes,
);
add(
  'an alert loses its class',
  ui,
  '<p data-kind={kind} role="alert" className={styles.alert}>',
  '<p data-kind={kind} role="alert">',
  view,
  classes,
);
add(
  'a notice sentence loses the class of its box',
  ui,
  '<div className={styles.noticeBody}>',
  '<div>',
  view,
  classes,
);
add(
  'the candidates lose their class',
  ui,
  '<ul className={styles.candidates}>',
  '<ul>',
  view,
  classes,
);
add(
  'the add button loses its class',
  ui,
  'className={styles.add}',
  '',
  view,
  classes,
);

// Check every anchor before starting baseline or mutating the isolated copy.
for (const c of cases) mutate(readFileSync(join(snapshot, c.file), 'utf8'), c);
if (
  run([tsc, '--noEmit', '--pretty', 'false'], 'baseline-types').status !== 0 ||
  run([vitest, 'run'], 'baseline-tests', 120000).status !== 0
)
  throw Error('Snapshot baseline failed');
const results = [];
for (const c of cases) {
  const file = join(snapshot, c.file),
    original = readFileSync(file, 'utf8');
  const changed = mutate(original, c),
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
