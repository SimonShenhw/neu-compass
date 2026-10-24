import { render } from '@testing-library/react';
import { expect, it } from 'vitest';
import { answerBlocks } from './answerText';
import type { AnswerBlock, Inline } from './answerText';
import { AnswerText } from '../features/search-answer/AnswerText';
import {
  fixtureTurn,
  loadExpected,
  readAnswerDOM,
  scenarios,
  settledTurns,
} from '../features/search-answer/searchTestUtils';
import { contextCourseIds, recentHistory } from './conversation';
import { incompleteTurn, newTurn, turnReducer } from './chatTurn';
import { scorePercent, scoreText } from './chatMeta';
import { chatFailureMessage, UNKNOWN_FAILURE } from './chatFailure';
import type { ChatFailure } from '../api/chat';

const vectors = loadExpected<
  { name: string; text: string; blocks: AnswerBlock[] }[]
>('answer-text-vectors.json');
it('freezes all 86 independent answer text vectors', () =>
  expect(vectors).toHaveLength(86));
it.each(vectors)('answer parser and real DOM: $name', ({ text, blocks }) => {
  expect(answerBlocks(text)).toEqual(blocks);
  const { container } = render(<AnswerText text={text} />);
  expect(readAnswerDOM(container.firstElementChild!)).toEqual(blocks);
  expect(container.querySelector('h1,h2,h3,h4,h5,h6,img,script,b')).toBeNull();
  for (const a of container.querySelectorAll('a')) {
    expect(a.getAttribute('href')).toMatch(
      /^https:\/\/catalog\.northeastern\.edu\/course-descriptions\/[a-z]{2,8}\/(#[A-Za-z0-9_-]{1,64})?$/,
    );
    expect(a).toHaveAttribute('target', '_blank');
    expect(a).toHaveAttribute('rel', 'noopener noreferrer');
  }
});
it('answer parser tolerates long plain lines and delimiter runs without pathological slowdown', () => {
  const text =
    '**<b>x</b>**\n' +
    'x'.repeat(100000) +
    '\n' +
    '*'.repeat(10000) +
    '\n' +
    '`'.repeat(10000);
  const start = performance.now();
  expect(answerBlocks(text).length).toBeGreaterThan(0);
  expect(performance.now() - start).toBeLessThan(1500);
});
// Each limit next to its first value past it; the blocks come from the same Python reference as the vectors.
const catalog = 'https://catalog.northeastern.edu/course-descriptions/cs/',
  anchored = `${catalog}#${'a'.repeat(64)}`,
  label = 'y'.repeat(200);
const paragraph = (...inlines: Inline[]): AnswerBlock[] => [
  { type: 'paragraph', inlines },
];
it.each([
  [
    'a 64-character anchor is part of the link',
    `[x](${anchored})`,
    paragraph({ t: 'link', v: 'x', href: anchored }),
  ],
  [
    'a 65-character anchor is not',
    `[x](${anchored}a)`,
    paragraph(
      { t: 'text', v: '[x](' },
      { t: 'link', v: anchored, href: anchored },
      { t: 'text', v: 'a)' },
    ),
  ],
  [
    'a 200-character label makes a link',
    `[${label}](${catalog})`,
    paragraph({ t: 'link', v: label, href: catalog }),
  ],
  [
    'a 201-character label does not',
    `[${label}y](${catalog})`,
    paragraph(
      { t: 'text', v: `[${label}y](` },
      { t: 'link', v: catalog, href: catalog },
      { t: 'text', v: ')' },
    ),
  ],
  [
    'tildes do not close a backtick fence',
    '```\n~~~\n代码\n```',
    [{ type: 'code', text: '~~~\n代码' }],
  ],
  [
    'backticks do not close a tilde fence',
    '~~~\n```\n代码\n~~~',
    [{ type: 'code', text: '```\n代码' }],
  ],
  [
    'a heading with nothing after the space is a paragraph',
    '# ',
    paragraph({ t: 'text', v: '#' }),
  ],
  [
    'a heading with nothing after the tab is a paragraph',
    '##\t',
    paragraph({ t: 'text', v: '##' }),
  ],
  [
    'nine digits start a list',
    '123456789. 九位',
    [
      {
        type: 'list',
        ordered: true,
        start: 123456789,
        items: [[{ t: 'text', v: '九位' }]],
      },
    ],
  ],
  [
    'ten digits are a paragraph',
    '1234567890. 十位',
    paragraph({ t: 'text', v: '1234567890. 十位' }),
  ],
] as [string, string, AnswerBlock[]][])(
  'answer parser limit: %s',
  (_name, text, blocks) => {
    expect(answerBlocks(text)).toEqual(blocks);
  },
);
const formats = loadExpected<
  { scores: number[]; rows: { score: number; text: string; pct: number }[] }[]
>('format-vectors.json');
it('search score exact Python format locks multiply-before-divide at a real rounding tie', () => {
  // Independently checked with Python round(): 100 * score / top is exactly 20.5,
  // whereas score / top * 100 is 20.500000000000004. The eight-percent floor cannot mask it.
  expect(scorePercent(0.020500000000000004, 0.1)).toBe(20);
});
it.each(formats.map((v, index) => ({ ...v, index })))(
  'search score exact Python format and multiply-before-divide width $index',
  ({ scores, rows }) => {
    const top = Math.max(...scores);
    expect(
      scores.map((score) => ({
        score,
        text: scoreText(score),
        pct: scorePercent(score, top),
      })),
    ).toEqual(rows);
  },
);
it.each(scenarios)(
  'search timeline and next request $caseName / $name',
  (scenario) => {
    expect(
      scenario.turns.map(
        (name, i) => fixtureTurn(name, i + 1, scenario.with_reason).timeline,
      ),
    ).toEqual(scenario.timeline);
    const turns = settledTurns(scenario);
    expect({
      history: recentHistory(turns),
      context_course_ids: contextCourseIds(turns),
    }).toEqual(scenario.next_request);
  },
);
it('turn reducer ignores impossible transitions and preserves identity for no-ops', () => {
  const waiting = newTurn(1, 'q', true);
  const token = { type: 'token' as const, text: 'x' },
    done = { type: 'done' as const, feedback: { raw: true } };
  expect(turnReducer(waiting, token)).toBe(waiting);
  expect(turnReducer(waiting, done)).toBe(waiting);
  const answering = turnReducer(waiting, {
    type: 'meta',
    meta: { matched_via: 'alias', results: [] },
  });
  expect(turnReducer(answering, { type: 'meta', meta: {} })).toBe(answering);
  const ended = turnReducer(answering, done);
  expect(ended.receipt).toBe(done.feedback);
  for (const event of [
    token,
    done,
    { type: 'error' as const, errorType: 'x', message: 'x' },
  ])
    expect(turnReducer(ended, event)).toBe(ended);
});
it('history slices six messages before removing blanks, truncates Unicode code points, and ignores active turns', () => {
  const turns = [
    newTurn(1, 'first', false),
    newTurn(2, 'second', false),
    newTurn(3, 'third', false),
    newTurn(4, 'fourth', false),
  ].map((t) => ({ ...t, status: 'done' as const, text: '' }));
  turns[3]!.text = '😀'.repeat(4001);
  expect(recentHistory(turns)).toEqual([
    { role: 'user', content: 'second' },
    { role: 'user', content: 'third' },
    { role: 'user', content: 'fourth' },
    { role: 'assistant', content: '😀'.repeat(4000) },
  ]);
  expect(recentHistory([...turns, newTurn(5, 'not ready', false)])).toEqual(
    recentHistory(turns),
  );
  const evidence = fixtureTurn('hybrid-neural-network').turn;
  if (evidence.meta?.kind !== 'ok') throw Error('fixture');
  const firstResult = evidence.meta.results[0]!;
  evidence.meta.results = Array.from({ length: 12 }, () => firstResult);
  expect(contextCourseIds([evidence, newTurn(2, 'waiting', false)])).toEqual(
    Array(10).fill(evidence.meta.results[0]!.course_id),
  );
});
it.each([
  [422, null, null, [], '这次提问的格式不对，没有发出去。请改一下再问。'],
  [
    408,
    null,
    null,
    [],
    '请求超时，处理可能仍在进行；请稍后手动重试，避免重复提交。',
  ],
  [
    504,
    null,
    null,
    [],
    '请求超时，处理可能仍在进行；请稍后手动重试，避免重复提交。',
  ],
  [
    502,
    'invalid_response',
    null,
    [],
    '服务返回了无法识别的内容，请稍后手动重试。',
  ],
  [500, null, null, [], '服务暂时出错，请稍后手动重试。'],
  [429, null, null, [], '请求过于频繁，请稍后手动重试。'],
  [503, 'service_busy', 0, [], '服务正忙，请0 秒后手动重试。'],
  [400, null, null, [], '请求未完成，请稍后手动重试。'],
] as const)(
  'failure message for %s',
  (status, errorType, retryAfter, invalidFields, text) => {
    expect(
      chatFailureMessage({
        status,
        errorType,
        retryAfter,
        invalidFields,
        reason: null,
      }),
    ).toBe(text);
  },
);
it('unknown failure never exposes raw error detail', () =>
  expect(chatFailureMessage(UNKNOWN_FAILURE)).toBe(
    '请求未完成，请稍后手动重试。',
  ));
it.each([
  [
    '422 naming the question among other fields',
    { status: 422, invalidFields: ['history', 'query'] },
    '问题最多 500 个字，这个问题没有发出去。请改短一点再问。',
  ],
  [
    '422 naming only other fields',
    { status: 422, invalidFields: ['history'] },
    '这次提问的格式不对，没有发出去。请改一下再问。',
  ],
  [
    '502 that is not an unreadable answer',
    { status: 502, errorType: 'upstream_error' },
    '服务暂时出错，请稍后手动重试。',
  ],
  [
    'a wait that is infinite',
    { status: 429, retryAfter: Infinity },
    '请求过于频繁，请稍后手动重试。',
  ],
  [
    'a wait that is not a number',
    { status: 503, retryAfter: NaN },
    '服务暂不可用，请稍后手动重试。',
  ],
] as [string, Partial<ChatFailure>, string][])(
  'failure message for %s',
  (_name, failure, text) => {
    expect(chatFailureMessage({ ...UNKNOWN_FAILURE, ...failure })).toBe(text);
  },
);
it('an unfinished stream stops with the spec sentence word for word', () => {
  expect(incompleteTurn(newTurn(1, 'q', false))).toMatchObject({
    status: 'stopped',
    error: {
      errorType: 'incomplete_stream',
      message: '回答流未完整结束；仅保留部分内容，请稍后手动重试。',
    },
  });
});
it('context course IDs skip a turn that is still running, even once its courses have arrived', () => {
  const ended = fixtureTurn('alias-cs-6140').turn,
    later = fixtureTurn('hybrid-neural-network', 2).turn;
  if (later.meta?.kind !== 'ok') throw Error('fixture');
  expect(contextCourseIds([ended, later])).toEqual(
    later.meta.results.map((r) => r.course_id),
  );
  expect(contextCourseIds([ended, { ...later, status: 'answering' }])).toEqual([
    'c-cs-6140',
  ]);
});
