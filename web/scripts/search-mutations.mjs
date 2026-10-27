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
  rmSync,
  symlinkSync,
  realpathSync,
  unlinkSync,
} from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { spawnSync } from 'node:child_process';

const root = process.cwd();
if (
  JSON.parse(readFileSync(join(root, 'package.json'), 'utf8')).name !==
  'neu-compass-web'
)
  throw Error('Run from web/');
// Everything the tests read besides src/; the baseline runs R2b's tests too, which read the last three.
const config = [
  'package.json',
  'package-lock.json',
  'tsconfig.json',
  'vite.config.ts',
  'eslint.config.js',
  'index.html',
  'openapi.json',
  'tools/openapi-types/package.json',
];
const paths = (dir) =>
  readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? paths(join(dir, e.name)) : [join(dir, e.name)],
  );
const hash = (file) =>
  createHash('sha256').update(readFileSync(file)).digest('hex');
const freeze = () =>
  Object.fromEntries(
    [
      ...paths(join(root, 'src')),
      ...paths(join(root, 'scripts')),
      ...config.map((f) => join(root, f)),
    ].map((f) => [f, hash(f)]),
  );
const frozen = freeze();
const output = join(
  root,
  'artifacts',
  'search-mutations-' + new Date().toISOString().replaceAll(/[:.]/g, '-'),
);
mkdirSync(output, { recursive: true });
const snapshot = mkdtempSync(
  join(realpathSync.native(tmpdir()), 'neu-search-'),
);
// The copy goes when the process exits, a failed baseline or a bad anchor included. Its junction goes first, so removing
// it cannot reach the node_modules behind it; if it cannot be removed, the copy stays. There is no signal handler: the
// run is synchronous, so one would only run after the last mutant, and Ctrl+C would no longer stop the run (R4c, as in
// draft-mutations.mjs).
process.on('exit', () => {
  const link = join(snapshot, 'node_modules');
  if (lstatSync(link, { throwIfNoEntry: false })?.isSymbolicLink())
    unlinkSync(link);
  if (existsSync(link))
    console.error('Copy kept, the link is still there: ' + snapshot);
  else rmSync(snapshot, { recursive: true, force: true });
});
cpSync(join(root, 'src'), join(snapshot, 'src'), { recursive: true });
for (const file of config) {
  mkdirSync(dirname(join(snapshot, file)), { recursive: true });
  cpSync(join(root, file), join(snapshot, file));
}
symlinkSync(
  resolve(root, 'node_modules'),
  join(snapshot, 'node_modules'),
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
    { flag: 'wx' },
  );
  return r;
}
console.info('Evidence: ' + output);
const baseline = run([vitest, 'run'], 'baseline-tests', 90000),
  types = run([tsc, '--noEmit'], 'baseline-types');
if (baseline.status !== 0 || types.status !== 0)
  throw Error('Unmutated snapshot must pass first');
const cases = [
  {
    id: 'S01',
    label: 'score binary half-even',
    file: 'src/models/chatMeta.ts',
    changes: [
      [
        'export function scoreText(score: number) {',
        'export function scoreText(score: number) { return score.toFixed(3);',
      ],
    ],
    test: 'src/models/searchCore.test.tsx',
    expected: 'search score exact Python format',
  },
  {
    id: 'S02',
    label: 'negative score sign',
    file: 'src/models/chatMeta.ts',
    changes: [["score < 0 || Object.is(score, -0) ? '-' : ''", "''"]],
    test: 'src/models/searchCore.test.tsx',
    expected: 'search score exact Python format',
  },
  {
    id: 'S03',
    label: 'signed zero score',
    file: 'src/models/chatMeta.ts',
    changes: [['score < 0 || Object.is(score, -0)', 'score < 0']],
    test: 'src/models/searchCore.test.tsx',
    expected: 'search score exact Python format',
  },
  {
    id: 'S04',
    label: 'multiply before divide',
    file: 'src/models/chatMeta.ts',
    changes: [
      ['roundEven((100 * score) / top)', 'roundEven((score / top) * 100)'],
    ],
    test: 'src/models/searchCore.test.tsx',
    expected: 'search score exact Python format',
  },
  {
    id: 'S05',
    label: 'minimum width eight',
    file: 'src/models/chatMeta.ts',
    changes: [[': 50, 8)', ': 50, 0)']],
    test: 'src/models/searchCore.test.tsx',
    expected: 'search score exact Python format',
  },
  {
    id: 'S06',
    label: 'first five missing labels',
    file: 'src/features/search-answer/SearchParts.tsx',
    changes: [['.slice(0, 5)', '.slice(0, 6)']],
    test: 'src/features/search-answer/SearchConversation.test.tsx',
    expected: 'compact evidence excludes',
  },
  {
    id: 'S07',
    label: 'only compact notices',
    file: 'src/features/search-answer/SearchParts.tsx',
    changes: [
      ['noticeLine(e.warnings, COMPACT_WARNINGS)', 'noticeLine(e.warnings)'],
    ],
    test: 'src/features/search-answer/SearchConversation.test.tsx',
    expected: 'compact evidence excludes',
  },
  {
    id: 'S08',
    label: 'unique descending requisite years',
    file: 'src/models/chatMeta.ts',
    changes: [['y >= years[i - 1]!', 'y > years[i - 1]!']],
    test: 'src/models/searchValidation.test.ts',
    expected: 'requisite year independent maximum',
  },
  {
    id: 'S09',
    label: 'storage rules constrain year evidence',
    file: 'src/models/chatMeta.ts',
    changes: [["(v.storage !== 'available' &&", '(false &&']],
    test: 'src/models/searchValidation.test.ts',
    expected: 'requisite year unavailable storage invariants',
  },
  {
    id: 'S10',
    label: 'unselected other-year count',
    file: 'src/models/chatMeta.ts',
    changes: [['(selected === null && others !== 0)', 'false']],
    test: 'src/models/searchValidation.test.ts',
    expected: 'requisite selected-year cardinality',
  },
  {
    id: 'S11',
    label: 'selected absent counts all other years',
    file: 'src/models/chatMeta.ts',
    changes: [['others !== editions.length + omitted', 'false']],
    test: 'src/models/searchValidation.test.ts',
    expected: 'requisite selected-year cardinality',
  },
  {
    id: 'S12',
    label: 'omitted years require exactly three editions',
    file: 'src/models/chatMeta.ts',
    changes: [['(omitted > 0 && editions.length !== 3)', 'false']],
    test: 'src/models/searchValidation.test.ts',
    expected: 'requisite selected-year cardinality',
  },
  {
    id: 'S13',
    label: 'plan keys match exact course identities',
    file: 'src/models/planContext.ts',
    changes: [['keys.some((k) => !courseIds.includes(k))', 'false']],
    test: 'src/models/searchValidation.test.ts',
    expected: 'plan dates, archive-year consistency',
  },
  {
    id: 'S14',
    label: 'checked date not before capture',
    file: 'src/models/planContext.ts',
    changes: [['v.checked_on < v.captured_on', 'false']],
    test: 'src/models/searchValidation.test.ts',
    expected: 'plan dates, archive-year consistency',
  },
  {
    id: 'S15',
    label: 'archive year matches plan',
    file: 'src/models/planContext.ts',
    changes: [['archive !== v.catalog_year', 'false']],
    test: 'src/models/searchValidation.test.ts',
    expected: 'plan dates, archive-year consistency',
  },
  {
    id: 'S16',
    label: 'feedback hash bound to exact answer',
    file: 'src/models/answerFeedback.ts',
    changes: [['hex === receipt.answer_sha256', 'true']],
    test: 'src/models/searchValidation.test.ts',
    expected: 'receipt is bound to exact UTF-8 text',
  },
  {
    id: 'S17',
    label: 'receipt disallows extra keys',
    file: 'src/models/answerFeedback.ts',
    changes: [
      ['    Object.keys(v).length !== 3 ||\n', ''],
      [
        "Object.keys(v).sort().join(',') !==\n      'answer_id,answer_sha256,feedback_token'",
        'false',
      ],
    ],
    test: 'src/models/searchValidation.test.ts',
    expected: 'receipt rejects',
  },
  {
    id: 'S18',
    label: 'response rating matches click',
    file: 'src/models/answerFeedback.ts',
    changes: [['v.rating === vote.rating', 'true']],
    test: 'src/models/searchValidation.test.ts',
    expected: 'feedback response requires exactly own keys',
  },
  {
    id: 'S19',
    label: 'only success records feedback',
    file: 'src/features/search-answer/AnswerFeedback.tsx',
    changes: [['if (feedbackResponseMatches(response, request))', 'if (true)']],
    test: 'src/features/search-answer/SearchConversation.test.tsx',
    expected: 'feedback synchronous lock prevents duplicate',
  },
  {
    id: 'S20',
    label: 'vote request exactly four fields',
    file: 'src/features/search-answer/AnswerFeedback.tsx',
    changes: [['rating: next,', 'rating: next, extra: true,']],
    test: 'src/features/search-answer/SearchConversation.test.tsx',
    expected: 'feedback synchronous lock prevents duplicate',
  },
  {
    id: 'S21',
    label: 'synchronous busy lock',
    file: 'src/features/search-answer/useConversation.ts',
    changes: [['owner.current !== null', 'false']],
    test: 'src/features/search-answer/useConversation.test.tsx',
    expected: 'hook synchronous busy lock refuses',
  },
  {
    id: 'S22',
    label: 'unmount aborts stream',
    file: 'src/features/search-answer/useConversation.ts',
    // R3e's reset() aborts too, so the anchor is the unmount cleanup's own (R4c).
    changes: [
      [
        'mounted.current = false;\n      owner.current?.abort();',
        'mounted.current = false;',
      ],
    ],
    test: 'src/features/search-answer/useConversation.test.tsx',
    expected: 'hook aborts on unmount',
  },
  {
    id: 'S23',
    label: 'invalid reducer transitions ignored',
    file: 'src/models/chatTurn.ts',
    changes: [["turn.status !== 'answering'", 'false']],
    test: 'src/models/searchCore.test.tsx',
    expected: 'turn reducer ignores impossible transitions',
  },
  {
    id: 'S24',
    label: 'six-message history window',
    file: 'src/models/conversation.ts',
    changes: [['.slice(-6)', '.slice(-8)']],
    test: 'src/models/searchCore.test.tsx',
    expected: 'history slices six messages before',
  },
  {
    id: 'S25',
    label: 'history codepoint truncation',
    file: 'src/models/conversation.ts',
    changes: [
      [
        "Array.from(m.content).slice(0, 4000).join('')",
        'm.content.slice(0, 4000)',
      ],
    ],
    test: 'src/models/searchCore.test.tsx',
    expected: 'history slices six messages before',
  },
  {
    id: 'S26',
    label: '409 reason controls wording',
    file: 'src/models/chatFailure.ts',
    changes: [[".get(reason ?? '')", ".get('')"]],
    test: 'src/features/search-answer/SearchConversation.golden.test.tsx',
    expected: 'search golden refused-409-plan-stale',
  },
  {
    id: 'S27',
    label: 'followups only last turn',
    file: 'src/features/search-answer/SearchConversation.tsx',
    changes: [['index === turns.length - 1', 'true']],
    test: 'src/features/search-answer/SearchConversation.test.tsx',
    expected: 'followups only occur on the last eligible',
  },
  {
    id: 'S28',
    label: 'rejected routes have no followups',
    file: 'src/features/search-answer/SearchConversation.tsx',
    changes: [
      ["!['rejected', 'empty'].includes(turn.meta.matched_via)", 'true'],
    ],
    test: 'src/features/search-answer/SearchConversation.test.tsx',
    expected: 'followups only occur on the last eligible',
  },
  {
    id: 'S29',
    label: 'model headings never affect page outline',
    file: 'src/features/search-answer/AnswerText.tsx',
    changes: [
      ['<p\n            key={index}', '<h3\n            key={index}'],
      ['</p>', '</h3>'],
    ],
    test: 'src/models/searchCore.test.tsx',
    expected: 'answer parser and real DOM',
  },
  {
    id: 'S30',
    label: 'catalog HTTPS only',
    file: 'src/models/answerText.ts',
    changes: [['https://catalog', 'https?://catalog']],
    test: 'src/models/searchCore.test.tsx',
    expected: 'answer parser and real DOM: http, another host',
  },
  {
    id: 'S31',
    label: 'bold inner whitespace stays literal',
    file: 'src/models/answerText.ts',
    changes: [
      [
        'const strong = /\\*\\*([^ \\t\\n*](?:[^*\\n]*[^ \\t\\n*])?)\\*\\*/gu;',
        'const strong = /\\*\\*([^\\n*](?:[^*\\n]*[^\\n*])?)\\*\\*/gu;',
      ],
    ],
    test: 'src/models/searchCore.test.tsx',
    expected: 'answer parser and real DOM: bold with a space',
  },
  {
    id: 'S32',
    label: 'unmount closes before late events',
    file: 'src/features/search-answer/useConversation.ts',
    changes: [
      [
        'for await (const event of source(controller.signal)) {\n          if (!active()) return;',
        'for await (const event of source(controller.signal)) {\n          if (false) return;',
      ],
    ],
    test: 'src/features/search-answer/useConversation.test.tsx',
    expected: 'hook aborts on unmount',
  },
];
cases.push(
  {
    id: 'S33',
    label: 'receipt field changes invalidate cached verification',
    file: 'src/features/search-answer/AnswerFeedback.tsx',
    changes: [
      [
        'verified.receipt.answer_id !== id ||\n    verified.receipt.answer_sha256 !== hash ||\n    verified.receipt.feedback_token !== token',
        'false',
      ],
    ],
    test: 'src/features/search-answer/SearchConversation.test.tsx',
    expected: 'feedback immediately rejects changed receipt fields',
  },
  {
    id: 'S34',
    label: 'duplicate result IDs keep Python last-record plan labels',
    file: 'src/features/search-answer/SearchParts.tsx',
    changes: [
      [
        'byId.get(id)',
        'meta.results.find((r) => r.course_id === id)?.primary_code',
      ],
    ],
    test: 'src/features/search-answer/SearchConversation.test.tsx',
    expected: 'plan placement labels use the last course record',
  },
);
cases.push(
  {
    id: 'S35',
    label: 'receipt rejects aliased comma-containing key names',
    file: 'src/models/answerFeedback.ts',
    changes: [['    Object.keys(v).length !== 3 ||\n', '']],
    test: 'src/models/searchValidation.test.ts',
    expected: 'receipt rejects comma-containing own keys',
  },
  {
    id: 'S36',
    label: 'feedback response rejects aliased comma-containing key names',
    file: 'src/models/answerFeedback.ts',
    changes: [['    Object.keys(v).length === 2 &&\n', '']],
    test: 'src/models/searchValidation.test.ts',
    expected: 'feedback response rejects comma-containing own keys',
  },
);
const results = [];
for (const c of cases) {
  const file = join(snapshot, c.file),
    original = readFileSync(file, 'utf8');
  let changed = original;
  for (const [from, to] of c.changes) {
    if (changed.split(from).length !== 2)
      throw Error(c.id + ': expected exactly one mutation anchor');
    changed = changed.replace(from, to);
  }
  const report = join(output, c.id + '.json');
  writeFileSync(file, changed);
  let r;
  try {
    r = run(
      [
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
  try {
    failures = JSON.parse(readFileSync(report, 'utf8')).testResults.flatMap(
      (s) =>
        s.assertionResults
          .filter((a) => a.status === 'failed')
          .map((a) => a.fullName),
    );
  } catch {
    /* Missing reports cannot count as a kill. */
  }
  const killed =
    !r.error && r.status === 1 && failures.some((n) => n.includes(c.expected));
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
    { baseline: 'passed', frozen, sourceUnchanged, snapshot, results },
    null,
    2,
  ),
  { flag: 'wx' },
);
console.info('Evidence: ' + output);
if (!sourceUnchanged || results.some((r) => !r.killed)) process.exitCode = 1;
